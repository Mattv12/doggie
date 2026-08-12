#!/usr/bin/env python3
"""Extra PiDog abilities, mixed into VoiceActiveDog:

- ears:  head turns toward sounds when idle (sound-direction sensor)
- guard: sits watching the camera; barks at strangers/motion, wags at the
         owner, saves alert photos to ~/pidog/guard_photos
- face:  simple owner recognition (enroll with "learn my face"); template
         matching on equalized 100x100 crops -- good enough for
         owner-vs-stranger in consistent garage lighting

House rule (same as balance/watch): exactly one mode owns the servos at a
time, enforced by guarded_run in voice_active_dog.py.
"""
import os
import random
import time
import threading
from pathlib import Path

from pidog.action_flow import ActionStatus, Posetures
from pidog.pidog import Pidog
from pidog.walk import Walk

FACES_DIR = "/home/matt/.pidog_faces/owner"
OWNER_EMBEDDINGS = "/home/matt/.pidog_faces/owner_embeddings.npy"
GUARD_DIR = "/home/matt/pidog/guard_photos"
VISITOR_FACES_DIR = "/home/matt/.pidog_faces/visitors"
OWNER_NAME = "Matt"
YUNET_MODEL = "/home/matt/.local/share/doggie/models/face_detection_yunet.onnx"
SFACE_MODEL = "/home/matt/.local/share/doggie/models/face_recognition_sface.onnx"


class AbilitiesMixin:

    GUARD_SAFE = ("bark", "bark harder", "wag tail")  # guard's own reactions
    GUARD_ALERT_COOLDOWN = 12.0
    VISITOR_RETENTION_SECONDS = 60 * 24 * 60 * 60
    VISITOR_FACE_SAVE_COOLDOWN = 20.0

    # ---------- shared mode plumbing ----------
    def _setup_abilities(self):
        ops = self.action_flow.OPERATIONS  # instance copy made in _setup_balance
        ops["guard on"] = {"function": lambda flow: self.start_guard()}
        ops["guard off"] = {"function": lambda flow: self.stop_guard()}
        ops["learn my face"] = {"function": lambda flow: self.learn_face()}
        ops["learn my voice"] = {"function": lambda flow: self.learn_voice()}
        # sit-only upward gaze (no "poseture" key: must not force a stand)
        ops["look up"] = {"function": lambda flow: self.look_up()}
        # smoother turns: stock 'turn left/right' walks a wide forward arc,
        # one gait cycle per command -> looks like a lurching shuffle. Pivot
        # gait instead: inside legs step backward at half stride, so the dog
        # rotates in place. Gyro A/B on hardware (2026-07-12): -0.5 inner
        # scale gave ~25% more yaw per cycle than stock at near-stock body
        # wobble; -1.0 and 0.0 both skid and rotate far less. Two continuous
        # cycles per command removes the single-cycle stutter.
        self._pivot_frames = {
            "left": self._make_pivot_frames([-0.5, 1, -0.5, 1]),
            "right": self._make_pivot_frames([1, -0.5, 1, -0.5]),
        }
        ops["turn left"] = {"function": lambda flow: self.pivot_turn("left"),
                            "poseture": Posetures.STAND}
        ops["turn right"] = {"function": lambda flow: self.pivot_turn("right"),
                             "poseture": Posetures.STAND}
        ops["turn around"] = {"function": lambda flow: self.pivot_turn("left", cycles=8),
                              "poseture": Posetures.STAND}
        self.guard_on = False
        self.guard_thread = None
        self._owner_samples = None
        self._owner_embeddings = None
        self._face_models_cache = None
        self._last_visitor_face_at = 0.0
        self._last_owner_face_at = 0.0
        self._start_head_life()

    def any_mode_on(self):
        return (self.balance_on or self.watch_on
                or getattr(self, "guard_on", False)
                )

    def stop_all_modes(self, keep=None):
        if keep != "balance":
            self.stop_balance()
        if keep != "watch":
            self.stop_watch()
        if keep != "guard":
            self.stop_guard()

    def _grab_gray(self, cv2):
        frame = self.picam2.capture_array()
        if frame.ndim == 3 and frame.shape[2] == 4:
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        else:
            bgr = frame
        if hasattr(self, "_brighten"):
            bgr = self._brighten(bgr, cv2)
        return bgr, cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    def _face_cascade(self, cv2):
        if getattr(self, "_cascade", None) is None:
            self._cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        return self._cascade

    def _face_models(self, cv2):
        if self._face_models_cache is not None:
            return self._face_models_cache
        if not (os.path.exists(YUNET_MODEL) and os.path.exists(SFACE_MODEL)):
            self._face_models_cache = False
            return False
        try:
            self._face_models_cache = (
                cv2.FaceDetectorYN.create(YUNET_MODEL, "", (320, 320), 0.78, 0.3, 100),
                cv2.FaceRecognizerSF.create(SFACE_MODEL, ""),
            )
        except Exception as exc:
            print(f"modern face models unavailable: {exc}")
            self._face_models_cache = False
        return self._face_models_cache

    def detect_faces(self, cv2, bgr, gray=None):
        models = self._face_models(cv2)
        if models:
            detector, _ = models
            detector.setInputSize((bgr.shape[1], bgr.shape[0]))
            _, faces = detector.detect(bgr)
            return [] if faces is None else list(faces)
        if gray is None:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return list(self._face_cascade(cv2).detectMultiScale(gray, 1.2, 4, minSize=(60, 60)))

    # ---------- pivot turns ----------
    @staticmethod
    def _make_pivot_frames(scales):
        class _PivotWalk(Walk):
            LEG_STEP_SCALES = [scales, scales, scales]  # same row for any lr
        gait = _PivotWalk(Walk.FORWARD, Walk.LEFT)
        return [Pidog.legs_angle_calculation(c) for c in gait.get_coords()]

    def pivot_turn(self, side, cycles=2):
        frames = self._pivot_frames[side]
        for _ in range(cycles):
            self.dog.legs_move(frames, immediately=False, speed=98)
        self.dog.wait_legs_done()

    # ---------- head life: idle curiosity + aroused glances ----------
    # One thread owns all ambient head motion. Two moods:
    #   idle    - every few seconds a small slow glance (yaw/pitch), with an
    #             occasional curious head tilt; ambient sound is ignored.
    #   aroused - for a few seconds after a wake word or while speaking:
    #             quicker, larger glances biased toward where the voice came
    #             from; decays back to idle when the timer runs out.
    # Idle glances target absolute angles near center, so the head naturally
    # drifts home without an explicit recenter step.
    HEAD_IDLE_GAP = (4.0, 9.0)    # s between idle glances
    HEAD_IDLE_YAW = 10            # deg, idle glance range (absolute)
    HEAD_IDLE_PITCH = 5
    HEAD_TILT_CHANCE = 0.2        # curious head-tilt probability per glance
    HEAD_TILT = (8, 16)           # deg tilt range
    HEAD_IDLE_SPEED = 18
    HEAD_AROUSED_GAP = (0.4, 1.2)
    HEAD_AROUSED_YAW = 26         # deg around the last heard direction
    HEAD_AROUSED_PITCH = 12
    # Wake-word motion must stay quiet enough for the microphone to hear the
    # command that immediately follows it.
    HEAD_AROUSED_SPEED = 30
    AROUSED_SOUND_COOLDOWN = 0.8  # min s between sound turns while aroused
    AROUSED_SOUND_DEADBAND = 10   # ignore sounds near current aim
    VISION_SURVEY_RANGE = (-10, 10)
    VISION_SURVEY_PITCH_RANGE = (2, 9)
    VISION_SURVEY_SPEED = 12
    VISION_SURVEY_STEP_GAP = 1.8
    VISION_SURVEY_DURATION = 7.0
    VISION_SURVEY_PITCH = 5

    # ---------- sit gaze: see more from the sit position ----------
    # Sitting tips the nose down (SIT head pitch comp is -35), so ambient
    # glances get an upward bias while sitting; the 'look up' voice command
    # (sit only) raises the gaze further and holds it for a while.
    HEAD_SIT_PITCH_BIAS = 12   # deg up, ambient glances while sitting
    HEAD_LOOKUP_PITCH = 28     # deg up for the 'look up' command
    HEAD_LOOKUP_HOLD = 45.0    # s the commanded up-gaze persists

    def _sitting(self):
        return getattr(self.action_flow, "posture", None) == Posetures.SIT

    def look_up(self):
        if not self._sitting():
            print("look up: only available while sitting")
            return
        self._sit_gaze_until = time.time() + self.HEAD_LOOKUP_HOLD
        self.dog.head_move([[0, 0, self.HEAD_LOOKUP_PITCH]],
                           pitch_comp=self.action_flow.head_pitch_init,
                           immediately=True, speed=40)
        print(f"look up: gazing up for {int(self.HEAD_LOOKUP_HOLD)}s")

    def _sit_pitch_bias(self, now):
        if not self._sitting():
            return 0
        if now < getattr(self, "_sit_gaze_until", 0):
            return self.HEAD_LOOKUP_PITCH
        return self.HEAD_SIT_PITCH_BIAS

    def head_excite(self, seconds=6.0, toward_sound=True):
        """Wake word / response: perk up and look toward the voice."""
        self._head_arousal_until = time.time() + seconds
        if toward_sound and not self.any_mode_on():
            try:
                yaw = getattr(self, "_last_wake_yaw", None)
                wake_age = time.time() - getattr(self, "_last_wake_direction_at", 0.0)
                if yaw is None or wake_age > 2.0:
                    yaw = self._direction_to_yaw(self.dog.ears.read())
                if yaw is not None:
                    self._sound_yaw = yaw
                    self.dog.head_move([[yaw, 0, 0]],
                                       pitch_comp=self.action_flow.head_pitch_init,
                                       immediately=True, speed=30)
                    self._head_yaw = yaw
            except Exception as e:
                print(f"head_excite error: {e}")

    @staticmethod
    def _direction_to_yaw(direction):
        # mapping from the stock 7_face_track.py example
        if 0 < direction < 160:
            return max(-80, -direction)
        if 200 < direction < 360:
            return min(80, 360 - direction)
        return None

    def _start_head_life(self):
        self._head_arousal_until = 0.0
        self._sit_gaze_until = 0.0
        self._sound_yaw = 0
        self._head_yaw = 0
        self._head_last_move = 0.0
        self._head_last_sound_turn = 0.0
        self._vision_survey_until = 0.0
        self._vision_survey_index = 0
        t = threading.Thread(name="head_life", target=self._head_life_loop, daemon=True)
        t.start()
        print("head life: idle curiosity + sound tracking")

    def start_visual_survey(self, seconds=None):
        duration = self.VISION_SURVEY_DURATION if seconds is None else seconds
        self._vision_survey_until = time.time() + duration
        self._vision_survey_index = 0
        self._head_last_move = 0.0
        try:
            pitch_comp = self.action_flow.head_pitch_init
            pitch = min(35, self.VISION_SURVEY_PITCH + self._sit_pitch_bias(time.time()))
            # Ease into the survey from center so visual questions feel calm.
            self.dog.head_move([[0, 0, pitch]], pitch_comp=pitch_comp,
                               immediately=True, speed=self.VISION_SURVEY_SPEED)
            self._head_yaw = 0
        except Exception as e:
            print(f"visual survey start error: {e}")

    def _head_life_loop(self):
        next_gap = random.uniform(*self.HEAD_IDLE_GAP)
        survey_points = [
            (0, self.VISION_SURVEY_PITCH),
            (self.VISION_SURVEY_RANGE[0], self.VISION_SURVEY_PITCH_RANGE[1]),
            (0, self.VISION_SURVEY_PITCH_RANGE[0]),
            (self.VISION_SURVEY_RANGE[1], self.VISION_SURVEY_PITCH_RANGE[1]),
            (0, self.VISION_SURVEY_PITCH),
        ]
        while True:
            try:
                time.sleep(0.05)
                now = time.time()
                if (self.any_mode_on()
                        or getattr(self, "_cmd_listening", False)
                        or not self.dog.is_head_done()):
                    continue
                aroused = now < self._head_arousal_until
                # idle glances only while the body is idle too; aroused ones
                # may play during think/say, but never stomp a queued head
                # animation (is_head_done above)
                if (not aroused and
                        self.action_flow.thread_action_state != ActionStatus.STANDBY):
                    continue
                pitch_comp = self.action_flow.head_pitch_init
                surveying = now < getattr(self, "_vision_survey_until", 0.0)

                if surveying:
                    if now - self._head_last_move < self.VISION_SURVEY_STEP_GAP:
                        continue
                    yaw, base_pitch = survey_points[self._vision_survey_index % len(survey_points)]
                    self._vision_survey_index += 1
                    pitch = min(35, base_pitch + self._sit_pitch_bias(now))
                    self.dog.head_move([[yaw, 0, pitch]], pitch_comp=pitch_comp,
                                       immediately=True, speed=self.VISION_SURVEY_SPEED)
                    self._head_yaw = yaw
                    self._head_last_move = now
                    continue

                # sound reorientation ONLY while aroused (after a wake word):
                # ambient noise at idle is ignored by design
                if aroused and self.dog.ears.isdetected():
                    yaw = self._direction_to_yaw(self.dog.ears.read())
                    if yaw is not None:
                        self._sound_yaw = yaw
                        if (now - self._head_last_sound_turn > self.AROUSED_SOUND_COOLDOWN
                                and abs(yaw - self._head_yaw) > self.AROUSED_SOUND_DEADBAND):
                            self.dog.head_move([[yaw, 0, 0]], pitch_comp=pitch_comp,
                                               immediately=True,
                                               speed=self.HEAD_AROUSED_SPEED)
                            self._head_yaw = yaw
                            self._head_last_sound_turn = now
                            self._head_last_move = now
                        continue

                # ambient glances
                if now - self._head_last_move < next_gap:
                    continue
                if aroused:
                    yaw = self._sound_yaw + random.uniform(
                        -self.HEAD_AROUSED_YAW, self.HEAD_AROUSED_YAW)
                    yaw = max(-80, min(80, yaw))
                    pitch = random.uniform(-self.HEAD_AROUSED_PITCH, self.HEAD_AROUSED_PITCH)
                    roll = random.uniform(-10, 10)
                    speed = self.HEAD_AROUSED_SPEED
                    next_gap = random.uniform(*self.HEAD_AROUSED_GAP)
                else:
                    yaw = random.uniform(-self.HEAD_IDLE_YAW, self.HEAD_IDLE_YAW)
                    pitch = random.uniform(-self.HEAD_IDLE_PITCH, self.HEAD_IDLE_PITCH)
                    roll = 0
                    if random.random() < self.HEAD_TILT_CHANCE:
                        roll = random.choice([-1, 1]) * random.uniform(*self.HEAD_TILT)
                    speed = self.HEAD_IDLE_SPEED
                    next_gap = random.uniform(*self.HEAD_IDLE_GAP)
                pitch = min(35, pitch + self._sit_pitch_bias(now))
                self.dog.head_move([[yaw, roll, pitch]], pitch_comp=pitch_comp,
                                   immediately=True, speed=speed)
                self._head_yaw = yaw
                self._head_last_move = now
            except Exception as e:
                print(f"head life error: {e}")
                time.sleep(1)

    # ---------- face recognition (owner vs stranger) ----------
    def _load_owner(self, cv2):
        if self._owner_samples is not None:
            return self._owner_samples
        samples = []
        if os.path.isdir(FACES_DIR):
            for f in sorted(os.listdir(FACES_DIR)):
                img = cv2.imread(os.path.join(FACES_DIR, f), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    samples.append(img)
        self._owner_samples = samples
        return samples

    def _crop_face(self, cv2, gray, face):
        x, y, w, h = (int(v) for v in face[:4])
        if gray is None or getattr(gray, "size", 0) == 0:
            return None
        # YuNet can report a box that slightly extends past the frame edge.
        # Clamp it before slicing so OpenCV never receives an empty crop.
        x = max(0, min(x, gray.shape[1]))
        y = max(0, min(y, gray.shape[0]))
        right = max(x, min(x + w, gray.shape[1]))
        bottom = max(y, min(y + h, gray.shape[0]))
        if right <= x or bottom <= y:
            return None
        crop = gray[y:bottom, x:right]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, (100, 100))
        return cv2.equalizeHist(crop)

    def _load_owner_embeddings(self):
        if self._owner_embeddings is None:
            try:
                import numpy as np
                self._owner_embeddings = np.load(OWNER_EMBEDDINGS)
            except (OSError, ValueError):
                self._owner_embeddings = []
        return self._owner_embeddings

    def _face_embedding(self, cv2, bgr, face):
        models = self._face_models(cv2)
        if not models:
            return None
        _, recognizer = models
        try:
            aligned = recognizer.alignCrop(bgr, face)
            return recognizer.feature(aligned)
        except Exception as exc:
            print(f"face embedding unavailable: {exc}")
            return None

    def _is_owner(self, cv2, gray, face, bgr=None):
        if bgr is not None:
            embedding = self._face_embedding(cv2, bgr, face)
            samples = self._load_owner_embeddings()
            if embedding is not None and len(samples):
                # SFace cosine matching is robust to pose/lighting unlike the
                # old equalized-pixel template comparison.
                _, recognizer = self._face_models(cv2)
                scores = [float(recognizer.match(
                    embedding, sample, cv2.FaceRecognizerSF_FR_COSINE))
                          for sample in samples]
                return max(scores, default=0.0) >= 0.45
        samples = self._load_owner(cv2)
        if not samples:
            return False
        crop = self._crop_face(cv2, gray, face)
        if crop is None:
            return False
        best = 0.0
        for s in samples:
            score = float(cv2.matchTemplate(crop, s, cv2.TM_CCOEFF_NORMED)[0][0])
            best = max(best, score)
        return best > 0.55

    def owner_face_status(self):
        """Return owner/non-owner when a clear face is visible, else None."""
        if getattr(self, "picam2", None) is None:
            return None
        try:
            import cv2
            if not self._load_owner(cv2):
                return None  # face enrollment has not happened yet
            bgr, gray = self._grab_gray(cv2)
            faces = self.detect_faces(cv2, bgr, gray)
            if len(faces) == 0:
                return None  # camera cannot help; fall back to voice
            return any(self._is_owner(cv2, gray, face, bgr) for face in faces)
        except Exception as exc:
            print(f"owner face check unavailable: {exc}")
            return None

    def remember_visible_face(self, cv2, bgr, gray, face):
        """Persist a visitor crop locally, or refresh the owner's memory."""
        if self._is_owner(cv2, gray, face, bgr):
            now = time.time()
            if (hasattr(self, "memory")
                    and now - getattr(self, "_last_owner_face_at", 0.0)
                    >= self.VISITOR_FACE_SAVE_COOLDOWN):
                self.memory.note_owner_seen(name=OWNER_NAME)
                self._last_owner_face_at = now
            return "owner"
        now = time.time()
        if now - getattr(self, "_last_visitor_face_at", 0.0) < self.VISITOR_FACE_SAVE_COOLDOWN:
            return "visitor"
        os.makedirs(VISITOR_FACES_DIR, exist_ok=True)
        crop = self._crop_face(cv2, gray, face)
        if crop is None:
            print("face memory: ignored invalid face crop")
            return "unavailable"
        path = os.path.join(VISITOR_FACES_DIR,
                            f"seen_{time.strftime('%Y-%m-%d_%H%M%S')}.png")
        cv2.imwrite(path, crop)
        self._last_visitor_face_at = now
        self._purge_expired_visitor_data()
        print(f"face memory: saved visitor face {path}")
        return "visitor"

    def _purge_expired_visitor_data(self):
        """Keep surveillance evidence local and remove it after 60 days.

        Owner enrollment samples live in ``FACES_DIR`` and are deliberately
        excluded, so they persist until the owner explicitly removes them.
        """
        cutoff = time.time() - self.VISITOR_RETENTION_SECONDS
        removed = 0
        for directory in (GUARD_DIR, VISITOR_FACES_DIR):
            path = Path(directory)
            if not path.is_dir():
                continue
            for item in path.iterdir():
                try:
                    if item.is_file() and not item.is_symlink() and item.stat().st_mtime < cutoff:
                        item.unlink()
                        removed += 1
                except OSError as exc:
                    print(f"retention cleanup warning for {item}: {exc}")
        if removed:
            print(f"retention cleanup: removed {removed} expired visitor item(s)")

    def learn_face(self):
        import cv2
        if getattr(self, "picam2", None) is None:
            print("learn face: no camera")
            return
        os.makedirs(FACES_DIR, exist_ok=True)
        self.tts.say(f"Okay {OWNER_NAME}, look at my nose for ten seconds.")
        got = 0
        embeddings = []
        t0 = time.time()
        while time.time() - t0 < 12 and got < 20:
            bgr, gray = self._grab_gray(cv2)
            faces = self.detect_faces(cv2, bgr, gray)
            if len(faces) > 0:
                face = max(faces, key=lambda f: f[2] * f[3])
                crop = self._crop_face(cv2, gray, face)
                if crop is None:
                    time.sleep(0.1)
                    continue
                cv2.imwrite(os.path.join(
                    FACES_DIR, f"owner_{int(time.time() * 1000)}.png"), crop)
                embedding = self._face_embedding(cv2, bgr, face)
                if embedding is not None:
                    embeddings.append(embedding)
                got += 1
            time.sleep(0.3)
        self._owner_samples = None  # force reload with the new samples
        if embeddings:
            import numpy as np
            np.save(OWNER_EMBEDDINGS, np.asarray(embeddings))
            self._owner_embeddings = None
        if got >= 8:
            if hasattr(self, "memory"):
                self.memory.note_owner_learned(name=OWNER_NAME, sample_count=got)
                self.memory.remember_note("Owner face was learned successfully.")
            self.tts.say(f"Got it. I will recognize you now, {OWNER_NAME}.")
        else:
            self.tts.say("I could not see your face well. Try again with more light.")
        print(f"learn face: saved {got} samples to {FACES_DIR}")

    def learn_voice(self):
        ok, message = self.voice_identity.enroll(self.tts.say)
        print(f"learn voice: {message}")
        self.tts.say(message)

    # ---------- guard mode ----------
    def start_guard(self):
        if getattr(self, "guard_on", False):
            return
        if getattr(self, "picam2", None) is None:
            print("guard: no camera")
            return
        self.guard_on = True
        self.guard_thread = threading.Thread(
            name="guard_loop", target=self._guard_loop, daemon=True)
        self.guard_thread.start()
        print("guard mode: ON")

    def stop_guard(self):
        if not getattr(self, "guard_on", False):
            return
        self.guard_on = False
        if self.guard_thread is not None and self.guard_thread is not threading.current_thread():
            self.guard_thread.join(timeout=3)
        self.guard_thread = None
        print("guard mode: OFF")

    def _guard_loop(self):
        import cv2
        os.makedirs(GUARD_DIR, exist_ok=True)
        os.makedirs(VISITOR_FACES_DIR, exist_ok=True)
        self._purge_expired_visitor_data()
        # face forward and hold still so frame-difference means real motion
        self.dog.head_move([[0, 0, 0]], pitch_comp=self.action_flow.head_pitch_init,
                           immediately=True, speed=80)
        self.dog.rgb_strip.set_mode('breath', 'red', 0.5)
        prev = None
        last_alert = 0
        next_cleanup = time.time() + 3600
        try:
            while self.guard_on:
                if time.time() >= next_cleanup:
                    self._purge_expired_visitor_data()
                    next_cleanup = time.time() + 3600
                bgr, gray = self._grab_gray(cv2)
                small = cv2.GaussianBlur(cv2.resize(gray, (160, 120)), (5, 5), 0)
                motion = False
                if prev is not None:
                    diff = cv2.absdiff(small, prev)
                    motion = int((diff > 28).sum()) > 350  # ~2% of pixels changed
                prev = small
                faces = self.detect_faces(cv2, bgr, gray)
                now = time.time()
                if (motion or len(faces) > 0) and now - last_alert > self.GUARD_ALERT_COOLDOWN:
                    last_alert = now
                    owner = any(self._is_owner(cv2, gray, f, bgr) for f in faces)
                    ts = time.strftime("%Y-%m-%d_%H%M%S")
                    path = os.path.join(GUARD_DIR, f"{ts}.jpg")
                    cv2.imwrite(path, bgr)
                    if owner:
                        if hasattr(self, "memory"):
                            self.memory.note_owner_seen(name=OWNER_NAME)
                        print(f"guard: owner recognized, photo {path}")
                        self.action_flow.add_action("wag tail")
                    else:
                        for index, face in enumerate(faces):
                            crop = self._crop_face(cv2, gray, face)
                            if crop is not None:
                                cv2.imwrite(os.path.join(
                                    VISITOR_FACES_DIR, f"{ts}_{index}.png"), crop)
                        print(f"GUARD ALERT: motion={motion} faces={len(faces)} photo {path}")
                        self.action_flow.add_action("bark harder")
                time.sleep(0.25)
        except Exception as e:
            print(f"guard loop error: {e}")
            self.guard_on = False
        finally:
            self.dog.rgb_strip.close()

