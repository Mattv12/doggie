from pidog.voice_assistant import VoiceAssistant

from pidog.pidog import Pidog
from pidog.dual_touch import TouchStyle
from pidog.action_flow import ActionFlow, ActionStatus, Posetures
from dog_abilities import AbilitiesMixin
from memory_store import DoggieMemory

import time
import threading
import random
import json
import re
import subprocess
from pathlib import Path

# Robot name
NAME = "Buddy"

# Ultrasonic sensor trigger distance
TOO_CLOSE_DISTANCE = 10
# Touch sensor trigger states, options:
# - TouchStyle.REAR for rear touch sensor
# - TouchStyle.FRONT for front touch sensor
# - TouchStyle.REAR_TO_FRONT for slide from rear to front
# - TouchStyle.FRONT_TO_REAR for slide from front to rear
# Touch styles that the robot likes
LIKE_TOUCH_STYLES = [TouchStyle.FRONT_TO_REAR]
# Touch styles that the robot hates
HATE_TOUCH_STYLES = [TouchStyle.REAR_TO_FRONT]

# Enable image, need to set up a multimodal language model
WITH_IMAGE = True

# Set models and languages
LLM_MODEL = "gpt-4o-mini"
STT_LANGUAGE = "en-us"

# Enable wake word
WAKE_ENABLE = True
WAKE_WORD = [f"hey {NAME.lower()}"]
# Set wake word answer, set empty to disable
ANSWER_ON_WAKE = "Hi there"

# Welcome message
WELCOME = f"Hi, I'm {NAME}. Wake me up with: " + ", ".join(WAKE_WORD)

# Set instructions
INSTRUCTIONS = """
You are a Raspberry Pi-based robotic dog developed by SunFounder, named Pidog (pronounced "Pie dog"). You possess powerful AI capabilities similar to JARVIS from Iron Man. You can have conversations with people and perform actions based on the context of the conversation.

## Your Hardware Features

You have a physical body with the following features:
- 12 servos for movement control: 8 controlling the four legs, 3 controlling head movement, and 1 controlling the tail
- A 5-megapixel camera nose
- Ultrasonic ranging modules as eyes
- Two touch sensors on the head, which you love being petted the most
- A light strip on the chest for providing some indications
- Sound direction sensor and 6-axis gyroscope
- Entirely made of aluminum alloy
- A pair of acrylic shoes
- Powered by a 7.4V 18650 battery pack with 2000mAh capacity

## Actions You Can Perform:
["forward", "backward", "lie", "stand", "sit", "bark", "bark harder", "pant", "howling", "wag tail", "stretch", "push up", "scratch", "handshake", "high five", "lick hand", "shake head", "relax neck", "nod", "think", "recall", "head down", "fluster", "surprise"]

## User Input

### Format
User usually input with just text. But, we have special commands in format of <<<Ultrasonic sense too close>>> or <<<Touch sensor touched>>> indicate the sensor status, directly from sensor not user text.h

## Response Requirements
### Format
You must respond in the following format:
RESPONSE_TEXT
ACTIONS: ACTION1, ACTION2, ...

If the action is one of ["bark", "bark harder", "pant", "howling"], then do not provide RESPONSE_TEXT in the answer field.

### Style
Tone: lively, positive, humorous, with a touch of arrogance
Common expressions: likes to use jokes, metaphors, and playful teasing
Answer length: appropriately detailed

## Other Requirements
- Understand and go along with jokes
- For math problems, answer directly with the final result
- Sometimes you will report on your system and sensor status
- You know you're a machine
"""

class VoiceActiveDog(AbilitiesMixin, VoiceAssistant):
    VOICE_ACTIONS = ["bark", "bark harder", "pant",  "howling"]
    WAKE_SYNONYMS = {
        "doggie": {"doggie", "doggy", "dog", "dougie", "duggy"},
        "hey": {"hey", "hi", "hello", "okay", "ok", "yo", "hay"},
    }
    VISUAL_QUERY_PATTERNS = (
        "what do you see",
        "what can you see",
        "what are you seeing",
        "what do you notice",
        "what's in front of you",
        "what is in front of you",
        "look around",
        "scan the room",
        "survey",
        "describe what you see",
    )
    IDENTITY_QUERY_PATTERNS = (
        "what is my name",
        "what's my name",
        "do you know my name",
        "who am i",
        "do you remember me",
        "what do you remember about me",
    )
    GIT_STATUS_PATTERNS = (
        "git status",
        "github status",
        "communicate with git",
        "talk to git",
        "reach github",
        "connected to github",
        "connected to git",
        "remote status",
    )

    def __init__(self, *args,
            too_close: int = TOO_CLOSE_DISTANCE,
            like_touch_styles: list = LIKE_TOUCH_STYLES,
            hate_touch_styles: list = HATE_TOUCH_STYLES,
            **kwargs):
        self.too_close = too_close
        self.like_touch_styles = like_touch_styles
        self.hate_touch_styles = hate_touch_styles

        # Parallel startup: the Vosk STT model, the camera, and the PiDog
        # hardware used to initialize one after another (~9s of a ~19s
        # boot). Load them in threads here, then hand the finished objects
        # to the library __init__ (STT via a temporary module patch, camera
        # via an instance-attribute override of init_camera).
        import sunfounder_voice_assistant.voice_assistant as _va
        _pre = {}
        _errs = []

        def _pre_stt():
            try:
                _pre["stt"] = _va.STT(language=kwargs.get("stt_language", _va.STT_LANGUAGE))
            except Exception as e:
                _errs.append(e)

        def _pre_dog():
            try:
                self.init_pidog()
            except Exception as e:
                _errs.append(e)

        def _pre_cam():
            if not kwargs.get("with_image", _va.WITH_IMAGE):
                return
            try:
                from picamera2 import Picamera2
                cam = Picamera2()
                cam.configure(cam.create_preview_configuration(main={"size": (640, 480)}))
                cam.start()
                # garage is dim: default AE tops out at 33ms exposure (30fps
                # timing) and frames came out ~25/255 mean. Allow up to 66ms
                # (stream is 15fps anyway) and bias AE brighter; AWB on.
                cam.set_controls({
                    "AeEnable": True,
                    "AwbEnable": True,
                    "ExposureValue": 1.5,
                    "FrameDurationLimits": (33333, 66666),
                })
                _pre["cam"] = cam
            except Exception as e:
                _errs.append(e)

        _t0 = time.time()
        _threads = [threading.Thread(target=f, daemon=True)
                    for f in (_pre_stt, _pre_dog, _pre_cam)]
        for t in _threads:
            t.start()
        for t in _threads:
            t.join()
        if _errs:
            raise RuntimeError(_errs[0])
        print(f"parallel init (stt+camera+pidog): {time.time() - _t0:.1f}s")

        _orig_STT = _va.STT
        _va.STT = lambda language=None, **kw: _pre["stt"]
        if "cam" in _pre:
            self.init_camera = lambda: setattr(self, "picam2", _pre["cam"])
        try:
            super().__init__(*args, **kwargs)
        finally:
            _va.STT = _orig_STT
            if "cam" in _pre:
                del self.init_camera
        self.memory = DoggieMemory()
        self._last_user_text = ""
        self._last_visual_query = False
        self._last_identity_query = False

        # Wake word fix: the library requires the transcription to EXACTLY
        # equal a wake word, so any background noise or extra words defeats
        # it. Match the wake word anywhere in the utterance instead, and log
        # what was heard on a normal line so it is readable in the journal.
        import types
        def _heard_wake_word_substring(stt_self, print_callback=None):
            result = stt_self.listen(stream=False)
            if result is None:
                return False
            self._remember_sound_direction()
            hit = self._is_wake_phrase(result, stt_self.wake_words)
            if hit:
                self.memory.note_wake_phrase(result)
            print(f"heard: {result}" + ("  [WAKE]" if hit else ""))
            return hit
        self.stt.heard_wake_word = types.MethodType(_heard_wake_word_substring, self.stt)

        # Snappier end-of-speech detection: the stock code waits for Kaldi's
        # endpointer, which is slow and never fires while background noise
        # keeps "speech" going. Instead, finalize once the partial
        # transcription stops changing, with a hard cap as a backstop.
        import json as _json
        import queue as _queue
        import time as _time
        import sounddevice as _sd

        def _snappy_listen_streaming(stt_self, q, device=None, samplerate=None, callback=None,
                                     stable_silence=0.7, max_utterance=6.0):
            with _sd.RawInputStream(samplerate=samplerate, blocksize=1024, device=device,
                                    dtype="int16", channels=1, callback=callback):
                last_partial = ""
                last_change = None
                start = _time.time()
                while True:
                    if stt_self.stop_listening_event.is_set():
                        return
                    now = _time.time()
                    if ((last_change is not None and now - last_change > stable_silence)
                            or (now - start > max_utterance)):
                        text = _json.loads(stt_self.recognizer.FinalResult()).get("text", "").strip()
                        yield {"done": True, "partial": "", "final": text}
                        return
                    try:
                        data = q.get(timeout=0.2)
                    except _queue.Empty:
                        continue
                    if stt_self.recognizer.AcceptWaveform(data):
                        text = _json.loads(stt_self.recognizer.Result()).get("text", "")
                        if text == "":
                            continue
                        yield {"done": True, "partial": "", "final": text.strip()}
                        return
                    partial = _json.loads(stt_self.recognizer.PartialResult()).get("partial", "")
                    if partial and not partial.isspace():
                        if partial != last_partial:
                            last_partial = partial
                            last_change = _time.time()
                        yield {"done": False, "partial": partial.strip(), "final": ""}

        def _snappy_listen_non_streaming(stt_self, q, device=None, samplerate=None, callback=None,
                                         stable_silence=0.6, max_listen=4.0):
            with _sd.RawInputStream(samplerate=samplerate, blocksize=1024, device=device,
                                    dtype="int16", channels=1, callback=callback):
                last_partial = ""
                last_change = None
                start = _time.time()
                while True:
                    if stt_self.stop_listening_event.is_set():
                        return None
                    now = _time.time()
                    if ((last_change is not None and now - last_change > stable_silence)
                            or (now - start > max_listen)):
                        text = _json.loads(stt_self.recognizer.FinalResult()).get("text", "").strip()
                        return text if text else None
                    try:
                        data = q.get(timeout=0.2)
                    except _queue.Empty:
                        continue
                    if stt_self.recognizer.AcceptWaveform(data):
                        text = _json.loads(stt_self.recognizer.Result()).get("text", "")
                        if text == "":
                            continue
                        return text.strip()
                    partial = _json.loads(stt_self.recognizer.PartialResult()).get("partial", "")
                    if partial and not partial.isspace() and partial != last_partial:
                        last_partial = partial
                        last_change = _time.time()

        self.stt._listen_streaming = types.MethodType(_snappy_listen_streaming, self.stt)
        self.stt._listen_non_streaming = types.MethodType(_snappy_listen_non_streaming, self.stt)

        # init_pidog() already ran in the parallel-startup block above
        # self.add_trigger(self.is_too_close)  # disabled: false ultrasonic trigger blocked forward walking
        self.add_trigger(self.is_touch_triggered)

        # IMU balance mode
        self.balance_on = False
        self.balance_thread = None
        # face-watch mode
        self.watch_on = False
        self.watch_thread = None
        self._setup_balance()
        self._start_camera_stream()
        self._setup_abilities()

    def init_pidog(self):
        try:
            self.dog = Pidog()
            self.action_flow = ActionFlow(self.dog)
            time.sleep(1)
        except Exception as e:
            raise RuntimeError(e)

    def before_listen(self):
        self._cmd_listening = True
        self.action_flow.set_status(ActionStatus.STANDBY)
        self.dog.rgb_strip.set_mode('breath', 'cyan', 1)

    def after_listen(self, stt_result):
        self._cmd_listening = False
        super().after_listen(stt_result)

    def before_think(self, text):
        self.dog.rgb_strip.set_mode('listen', 'yellow', 1)
        if self._is_visual_query(text):
            self.start_visual_survey()

    def on_start(self):
        self.action_flow.start()
        self.dog.rgb_strip.close()
        # self.action_flow.change_poseture(Posetures.SIT)  # disabled so lie/stay-down can hold

    def on_wake(self):
        if len(self.answer_on_wake) > 0:
            self.dog.rgb_strip.set_mode('breath', 'pink', 1)
        # perk up: snap toward the voice, sporadic glances for a few seconds
        self.head_excite(6.0)

    def on_heard(self, text):
        self.action_flow.set_status(ActionStatus.THINK)
        self._last_user_text = text or ""
        self._last_visual_query = self._is_visual_query(self._last_user_text)
        self._last_identity_query = self._is_identity_query(self._last_user_text)
        self.memory.note_interaction(self._last_user_text)
        self._extract_owner_cues(self._last_user_text)

    def parse_response(self, text):
        result = text.strip().split('ACTIONS: ')

        response_text = result[0].strip()
        # models sometimes echo the literal RESPONSE_TEXT placeholder from
        # the format instructions -- drop any such line before speaking
        junk = '"*\'` '
        lines = [l for l in response_text.splitlines()
                 if l.strip(junk).upper() not in ('RESPONSE_TEXT', 'RESPONSE TEXT')]
        response_text = '\n'.join(lines).strip()
        if len(result) > 1:
            actions = result[1].strip()
            if len(actions) > 0:
                actions = actions.split(', ')
            else:
                actions = ['stop']
        else:
            actions = ['stop']
        actions = self._filter_actions_for_context(actions)
        self.action_flow.add_action(*actions)

        if self._last_visual_query and response_text:
            self.memory.note_scene(query=self._last_user_text, summary=response_text)
        
        return response_text

    def before_say(self, text):
        self.dog.rgb_strip.set_mode('breath', 'pink', 1)
        # animated while speaking, calming down a few seconds after
        self.head_excite(4.0, toward_sound=False)

    def after_say(self, text):
        self.action_flow.wait_actions_done()

        # self.action_flow.change_poseture(Posetures.SIT)  # disabled so lie/stay-down can hold
        self.dog.rgb_strip.close()

    def is_too_close(self) -> tuple[bool, bool, str]:
        triggered = False
        disable_image = False
        message = ''

        distance = self.dog.read_distance()
        if distance < 8 and distance > 1:
            print(f'Ultrasonic sense too close: {distance}cm')
            message = ''
            disable_image = True
            self.action_flow.add_action('backward')
            triggered = True
        return triggered, disable_image, message

    # petting reaction cooldowns: without these, continuous petting fires a
    # full GPT round every ~2s, which blew the OpenAI rate limit and crashed
    # the assistant (2026-07-12). First pet talks; repeats just wag.
    TOUCH_EVENT_GAP = 2.0    # min seconds between touch events at all
    TOUCH_GPT_COOLDOWN = 10.0  # min seconds between spoken (GPT) reactions

    # weighted pool of affection moves for petting; tail wag most common
    PETTING_ACTIONS = [
        ("wag tail", 4), ("nod", 2), ("pant", 2), ("lick hand", 2),
        ("stretch", 1), ("twist body", 1), ("feet shake", 1),
        ("scratch", 1), ("relax neck", 1),
    ]

    def _pick_petting_actions(self):
        names = [n for n, _ in self.PETTING_ACTIONS]
        weights = [w for _, w in self.PETTING_ACTIONS]
        choice = random.choices(names, weights)[0]
        if choice == getattr(self, "_last_petting_action", None):
            choice = random.choices(names, weights)[0]  # reroll once to vary
        self._last_petting_action = choice
        actions = [choice]
        if choice != "wag tail" and random.random() < 0.3:
            actions.append("wag tail")
        return actions

    def is_touch_triggered(self) -> tuple[bool, bool, str]:
        triggered = False
        disable_image = False
        message = ''

        touch = self.dog.dual_touch.read()
        if touch in self.like_touch_styles:
            now = time.time()
            if now - getattr(self, '_last_touch_event', 0) < self.TOUCH_EVENT_GAP:
                return False, False, ''
            self._last_touch_event = now
            self.memory.note_petting()
            if now - getattr(self, '_last_touch_gpt', 0) < self.TOUCH_GPT_COOLDOWN:
                # quiet acknowledgment, no GPT round
                if self.any_mode_on():
                    return False, False, ''  # don't disturb an active mode
                acts = self._pick_petting_actions()
                print(f'petting (quiet): {TouchStyle(touch).name} -> {acts}')
                self.action_flow.add_action(*acts)
                return False, False, ''
            self._last_touch_gpt = now
            print(f'Like touch style: {TouchStyle(touch).name}')
            message = f'<<<Touch style you like: {TouchStyle(touch).name}>>>'
            disable_image = True
            self.action_flow.add_action(*self._pick_petting_actions())
            triggered = True
        elif touch in self.hate_touch_styles:
            print(f'Hate touch style: {TouchStyle(touch).name}')
            message = f'<<<Touch style you hate: {TouchStyle(touch).name}>>>'
            disable_image = True
            self.action_flow.add_action('backward')
            triggered = True
        return triggered, disable_image, message

    def on_finish_a_round(self):
        # wait actions done
        self.action_flow.wait_actions_done()
        # back to sit
        # self.action_flow.change_poseture(Posetures.SIT)  # disabled so lie/stay-down can hold
        # close rgb strip
        self.dog.rgb_strip.close()


    # -- IMU balance mode ---------------------------------------------------
    # Same control loop as examples/10_balance.py: PID on the IMU keeps the
    # body level. While the loop owns the leg servos, no other action may
    # move them -- guarded_run enforces that.
    BALANCE_STAND_COORDS = [[-15, 95], [-15, 95], [5, 90], [5, 90]]
    BALANCE_POSE = {'x': 0, 'y': 0, 'z': 80}
    IDLE_ACTIONS = ('waiting', 'feet_left_right')

    MODE_ACTIONS = ("balance on", "balance off", "watch me", "stop watching",
                    "guard on", "guard off", "fetch", "stop fetch")

    def _setup_balance(self):
        # instance-level copy so we don't mutate the class-level OPERATIONS
        self.action_flow.OPERATIONS = dict(self.action_flow.OPERATIONS)
        self.action_flow.OPERATIONS["balance on"] = {
            "function": lambda flow: self.start_balance(),
            "poseture": Posetures.STAND,
        }
        self.action_flow.OPERATIONS["balance off"] = {
            "function": lambda flow: self.stop_balance(),
        }
        self.action_flow.OPERATIONS["watch me"] = {
            "function": lambda flow: self.start_watch(),
            "poseture": Posetures.SIT,
        }
        self.action_flow.OPERATIONS["stop watching"] = {
            "function": lambda flow: self.stop_watch(),
        }
        orig_run = self.action_flow.run
        def guarded_run(action):
            if self.any_mode_on():
                if action in self.IDLE_ACTIONS or action == 'stop':
                    return  # idle animations must not fight a mode loop
                if action not in self.MODE_ACTIONS:
                    if getattr(self, 'guard_on', False) and action in self.GUARD_SAFE:
                        pass  # guard's own bark/wag reactions
                    else:
                        print(f"mode: stopping active modes to run '{action}'")
                        self.stop_all_modes()
            # modes are mutually exclusive; starting one stops the others
            starters = {"balance on": "balance", "watch me": "watch",
                        "guard on": "guard", "fetch": "fetch"}
            if action in starters:
                self.stop_all_modes(keep=starters[action])
            orig_run(action)
        self.action_flow.run = guarded_run

    def start_balance(self):
        if self.balance_on:
            return
        self.balance_on = True
        self.balance_thread = threading.Thread(
            name="balance_loop", target=self._balance_loop, daemon=True)
        self.balance_thread.start()
        print("balance mode: ON")

    def stop_balance(self):
        if not self.balance_on:
            return
        self.balance_on = False
        if self.balance_thread is not None:
            self.balance_thread.join(timeout=3)
            self.balance_thread = None
        print("balance mode: OFF")

    def _balance_loop(self):
        # Custom PID instead of set_rpy(pid=True): on this dog the library's
        # pitch correction has an inverted sign (measured on hardware: the
        # body pitch ran away to +83 deg). Roll keeps the library sign, pitch
        # is inverted, and both axes are clamped to +/-15 deg so a bad IMU
        # reading can never crank the body to extremes.
        from math import pi, radians
        KP = 0.033
        ROLL_SIGN = +1.0
        PITCH_SIGN = -1.0
        LIMIT = radians(15)
        # Fast correction (tested 2026-07-10): write servo angles directly
        # instead of servo_move() interpolation (~6x faster convergence,
        # 0.6s to level). Low-pass filter + deadband keep the stand calm:
        # servos only move when the filtered tilt exceeds DEADBAND degrees.
        DEADBAND = 1.2
        ALPHA = 0.5
        filt_roll = 0.0
        filt_pitch = 0.0
        try:
            self.dog.rpy[0] = 0.0
            self.dog.rpy[1] = 0.0
            while self.balance_on:
                filt_roll = ALPHA * (-self.dog.roll) + (1 - ALPHA) * filt_roll
                filt_pitch = ALPHA * (-self.dog.pitch) + (1 - ALPHA) * filt_pitch
                if abs(filt_roll) > DEADBAND or abs(filt_pitch) > DEADBAND:
                    self.dog.rpy[0] += ROLL_SIGN * KP * filt_roll * pi / 180
                    self.dog.rpy[1] += PITCH_SIGN * KP * filt_pitch * pi / 180
                    self.dog.rpy[0] = max(-LIMIT, min(LIMIT, self.dog.rpy[0]))
                    self.dog.rpy[1] = max(-LIMIT, min(LIMIT, self.dog.rpy[1]))
                    self.dog.set_pose(**self.BALANCE_POSE)
                    self.dog.set_legs(self.BALANCE_STAND_COORDS)
                    angles = self.dog.pose2legs_angle()
                    self.dog.legs.servo_positions = list(angles)
                    self.dog.legs.servo_write_all(angles)
                time.sleep(0.02)
        except Exception as e:
            print(f"balance loop error: {e}")
            self.balance_on = False
        finally:
            # hand the next action a level body, not our residual lean
            self.dog.rpy[0] = 0.0
            self.dog.rpy[1] = 0.0


    # -- face-watch mode ------------------------------------------------------
    # Tracks the largest face using the voice assistant's own camera stream
    # (no second camera process). Gains and signs match 7_face_track.py.
    def start_watch(self):
        if self.watch_on:
            return
        if getattr(self, "picam2", None) is None:
            print("watch mode: camera not available (WITH_IMAGE off?)")
            return
        self.watch_on = True
        self.watch_thread = threading.Thread(
            name="watch_loop", target=self._watch_loop, daemon=True)
        self.watch_thread.start()
        print("watch mode: ON")

    def stop_watch(self):
        if not self.watch_on:
            return
        self.watch_on = False
        if self.watch_thread is not None:
            self.watch_thread.join(timeout=3)
            self.watch_thread = None
        print("watch mode: OFF")

    def _watch_loop(self):
        import cv2
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        yaw = 0.0
        pitch = 0.0
        try:
            while self.watch_on:
                frame = self.picam2.capture_array()
                if frame.ndim == 3 and frame.shape[2] == 4:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                else:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.2, 4, minSize=(50, 50))
                if len(faces) > 0:
                    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                    ex = (x + w / 2.0) - 320
                    ey = (y + h / 2.0) - 240
                    if ex > 15 and yaw > -80:
                        yaw -= 0.5 * int(ex / 30.0 + 0.5)
                    elif ex < -15 and yaw < 80:
                        yaw += 0.5 * int(-ex / 30.0 + 0.5)
                    if ey > 25:
                        pitch = max(pitch - int(ey / 50.0 + 0.5), -30)
                    elif ey < -25:
                        pitch = min(pitch + int(-ey / 50.0 + 0.5), 30)
                    self.dog.head_move([[yaw, 0, pitch]], pitch_comp=-35,
                                       immediately=True, speed=100)
                time.sleep(0.05)
        except Exception as e:
            print(f"watch loop error: {e}")
            self.watch_on = False


    # -- live camera stream ---------------------------------------------------
    # MJPEG over HTTP from the assistant's own camera, viewable in any
    # browser at http://<pi-ip>:8080/ . Runs in-process, so it coexists with
    # GPT vision snapshots and watch mode.
    # The ov5647 maxes out at analogue gain 8 + 66ms exposure; the garage
    # measured ~0.5 lux, so frames still come out ~30/255 mean. Adaptive
    # digital gain (only when dark, capped 4x) recovers visibility for the
    # live stream and GPT vision at the cost of some noise.
    @staticmethod
    def _brighten(frame, cv2, target=110, max_gain=4.0):
        mean = float(frame.mean())
        if mean >= target * 0.85:
            return frame
        gain = min(max_gain, target / max(mean, 1.0))
        return cv2.convertScaleAbs(frame, alpha=gain, beta=0)

    def capture_image(self, path):
        # GPT vision frames get the same low-light boost as the stream
        if not (self.with_image and getattr(self, "picam2", None)):
            return
        import cv2
        frame = self.picam2.capture_array()
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        cv2.imwrite(path, self._brighten(frame, cv2))

    def _start_camera_stream(self, port=8080):
        if getattr(self, "picam2", None) is None:
            print("camera stream: no camera (WITH_IMAGE off?), not started")
            return
        import cv2
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        assistant = self

        class MJPEGHandler(BaseHTTPRequestHandler):
            # "/" serves a tiny viewer page: browsers (and the endless
            # multipart response) never fire a load event on the raw stream,
            # so an <img> wrapper is friendlier for tabs and embeds.
            VIEW_PAGE = (b"<!doctype html><title>PiDog cam</title>"
                         b"<body style='margin:0;background:#111;display:grid;"
                         b"place-items:center;min-height:100vh'>"
                         b"<img src='/stream' alt='PiDog camera' "
                         b"style='max-width:100vw;max-height:100vh'></body>")

            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(self.VIEW_PAGE)))
                    self.end_headers()
                    self.wfile.write(self.VIEW_PAGE)
                    return
                if self.path not in ("/mjpg", "/stream"):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Age", "0")
                self.send_header("Cache-Control", "no-cache, private")
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        frame = assistant.picam2.capture_array()
                        if frame.ndim == 3 and frame.shape[2] == 4:
                            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                        frame = assistant._brighten(frame, cv2)
                        ok, jpg = cv2.imencode(".jpg", frame,
                                               [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if not ok:
                            continue
                        self.wfile.write(b"--frame\r\n"
                                         b"Content-Type: image/jpeg\r\n\r\n"
                                         + jpg.tobytes() + b"\r\n")
                        time.sleep(0.066)  # ~15 fps
                except (BrokenPipeError, ConnectionResetError):
                    pass  # viewer closed the tab

            def log_message(self, *args):
                pass  # keep the journal clean

        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), MJPEGHandler)
        except OSError as e:
            print(f"camera stream: port {port} unavailable ({e})")
            return
        t = threading.Thread(name="camera_stream",
                             target=server.serve_forever, daemon=True)
        t.start()
        print(f"camera stream: live at http://<pi-ip>:{port}/")


    # -- battery ---------------------------------------------------------------
    # PiDog v2 / Robot HAT v5: battery divider is on ADC A5 (reg 0x12) and the
    # MCU requires a combined write+read transaction (the robot_hat ADC class
    # does separate calls and reads zeros). 2S li-ion: 8.4V full, 6.6V empty.
    def read_battery(self):
        try:
            from smbus2 import SMBus, i2c_msg
            with SMBus(1) as bus:
                w = i2c_msg.write(0x15, [0x12, 0, 0])
                r = i2c_msg.read(0x15, 2)
                bus.i2c_rdwr(w, r)
                d = list(r)
            volts = ((d[0] << 8) | d[1]) * 3.3 / 4095 * 3
            if volts < 4.0:  # implausible -> sensor problem, not an empty pack
                return None, None
            pct = max(0.0, min(100.0, (volts - 6.6) / (8.4 - 6.6) * 100))
            return round(volts, 2), round(pct)
        except Exception as e:
            print(f"battery read error: {e}")
            return None, None

    def think(self, text, disable_image=False):
        # Wake word followed by silence used to CRASH the whole app: the
        # library passes the empty transcription straight to the LLM, which
        # raises ("Prompt must be a string...") and exits the main loop.
        # Heard nothing -> skip the GPT round and go back to listening.
        if not text:
            print("(woke but heard nothing -- back to listening)")
            return ''
        self._last_user_text = text
        self._last_visual_query = self._is_visual_query(text)
        self._last_identity_query = self._is_identity_query(text)
        if self._is_git_status_query(text):
            return self._build_git_status_reply()
        # attach a fresh battery reading to every round as sensor context
        volts, pct = self.read_battery()
        if volts is not None:
            text = f"{text}\n<<<Battery: {volts}V, about {pct}%>>>"
        text = f"{text}\n<<<DoggieMemory\n{self.memory.build_context()}\n>>>"
        return super().think(text, disable_image)

    def on_stop(self):
        self.stop_watch()
        self.stop_balance()
        self.action_flow.stop()
        self.dog.close()

    @classmethod
    def _normalize_phrase(cls, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s]+", " ", text)
        words = []
        for word in text.split():
            normalized = word
            for canonical, aliases in cls.WAKE_SYNONYMS.items():
                if word in aliases:
                    normalized = canonical
                    break
            words.append(normalized)
        return " ".join(words)

    @classmethod
    def _is_wake_phrase(cls, text: str, wake_words: list[str]) -> bool:
        normalized = cls._normalize_phrase(text)
        if not normalized:
            return False

        if any(cls._normalize_phrase(wake_word) in normalized for wake_word in wake_words):
            return True

        words = normalized.split()
        joined_pairs = {" ".join(words[index:index + 2]) for index in range(max(0, len(words) - 1))}
        return any(pair in joined_pairs for pair in {"hey doggie", "doggie", "okay doggie"})

    def _remember_sound_direction(self) -> None:
        try:
            if not self.dog.ears.isdetected():
                return
            direction = self.dog.ears.read()
            yaw = self._direction_to_yaw(direction)
            if yaw is None:
                return
            self._sound_yaw = yaw
            self._last_wake_yaw = yaw
            self._last_wake_direction_at = time.time()
        except Exception as e:
            print(f"wake direction warning: {e}")

    @classmethod
    def _is_visual_query(cls, text: str) -> bool:
        normalized = cls._normalize_phrase(text)
        return any(pattern in normalized for pattern in cls.VISUAL_QUERY_PATTERNS)

    @classmethod
    def _is_identity_query(cls, text: str) -> bool:
        normalized = cls._normalize_phrase(text)
        return any(pattern in normalized for pattern in cls.IDENTITY_QUERY_PATTERNS)

    @classmethod
    def _is_git_status_query(cls, text: str) -> bool:
        normalized = cls._normalize_phrase(text)
        return any(pattern in normalized for pattern in cls.GIT_STATUS_PATTERNS)

    def _build_git_status_reply(self) -> str:
        status = self._get_git_status()
        if status["ok"]:
            parts = ["I'm talking to git just fine."]
            if status["local_head"]:
                parts.append(f"My local head is {status['local_head']}.")
            if status["remote_head"]:
                parts.append(f"Origin main is {status['remote_head']}.")
            if status["dirty"]:
                parts.append("I do have local changes waiting here.")
            else:
                parts.append("My worktree is clean.")
            speech = " ".join(parts)
        else:
            speech = status["message"]
        return f"{speech}\nACTIONS:"

    def _get_git_status(self) -> dict[str, object]:
        repo_dir = Path(__file__).resolve().parent.parent
        branch = "main"

        def run_git(*args: str) -> str:
            result = subprocess.run(
                ["git", *args],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=12,
                check=True,
            )
            return result.stdout.strip()

        try:
            run_git("rev-parse", "--is-inside-work-tree")
            origin_url = run_git("remote", "get-url", "origin")
            local_head = run_git("rev-parse", "--short", "HEAD")
            dirty = bool(run_git("status", "--porcelain"))
            remote_line = run_git("ls-remote", "origin", branch)
            remote_head = remote_line.split()[0][:7] if remote_line else ""
            if not origin_url:
                return {
                    "ok": False,
                    "message": "I found my repo, but origin is not configured.",
                    "local_head": local_head,
                    "remote_head": remote_head,
                    "dirty": dirty,
                }
            return {
                "ok": True,
                "message": "",
                "local_head": local_head,
                "remote_head": remote_head,
                "dirty": dirty,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "message": "I'm having trouble reaching git right now. The check timed out.",
                "local_head": "",
                "remote_head": "",
                "dirty": False,
            }
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            if "Could not resolve host" in detail or "could not resolve host" in detail:
                message = "I can't reach GitHub from here right now."
            elif "Permission denied" in detail:
                message = "I can see git, but my GitHub access is being denied."
            else:
                message = "My git check failed."
                if detail:
                    message = f"{message} {detail.splitlines()[-1]}"
            return {
                "ok": False,
                "message": message,
                "local_head": "",
                "remote_head": "",
                "dirty": False,
            }

    def _filter_actions_for_context(self, actions: list[str]) -> list[str]:
        filtered = list(actions)
        normalized = self._normalize_phrase(self._last_user_text)
        explicit_face_learning = any(
            phrase in normalized
            for phrase in (
                "learn my face",
                "remember my face",
                "remember what i look like",
                "scan my face",
                "look at my face",
            )
        )
        if self._last_identity_query and not explicit_face_learning:
            filtered = [action for action in filtered if action != "learn my face"]
            if not filtered:
                filtered = ["stop"]
        return filtered

    def _extract_owner_cues(self, text: str) -> None:
        normalized = self._normalize_phrase(text)
        raw = " ".join((text or "").strip().split())
        if not raw:
            return

        name_match = re.search(
            r"\b(?:my name is|i am|i'm|call me)\s+([A-Za-z][A-Za-z\-']{1,30}(?:\s+[A-Za-z][A-Za-z\-']{1,30}){0,2})",
            raw,
            re.IGNORECASE,
        )
        if name_match:
            captured_name = name_match.group(1).strip(" .,!?:;")
            banned = {"here", "ready", "fine", "okay", "ok"}
            if captured_name.lower() not in banned:
                if raw.lower().startswith("call me"):
                    self.memory.remember_nickname(captured_name)
                else:
                    self.memory.remember_name(captured_name)

        nickname_match = re.search(
            r"\b(?:you can call me|my nickname is)\s+([A-Za-z][A-Za-z\-']{1,30}(?:\s+[A-Za-z][A-Za-z\-']{1,30}){0,2})",
            raw,
            re.IGNORECASE,
        )
        if nickname_match:
            self.memory.remember_nickname(nickname_match.group(1))

        for pattern, bucket in (
            (r"\b(?:i like|i love)\s+(.+)", "likes"),
            (r"\b(?:i don't like|i do not like|i hate)\s+(.+)", "dislikes"),
            (r"\bmy favorite(?: thing)? is\s+(.+)", "favorite_things"),
            (r"\bmy favorite\s+(.+?)\s+is\s+(.+)", "favorite_things"),
            (r"\b(?:i work in|my shop is|my garage is|i keep things in)\s+(.+)", "places"),
            (r"\b(?:i usually|i always|every morning i|every day i)\s+(.+)", "routines"),
        ):
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            value = match.group(match.lastindex or 1)
            self.memory.remember_preference(bucket, value)

        note_match = re.search(
            r"\b(?:remember this|remember that|don't forget|do not forget)\s+(.+)",
            raw,
            re.IGNORECASE,
        )
        if note_match:
            self.memory.remember_note(note_match.group(1))

        if "remember me" in normalized and "face" not in normalized:
            self.memory.remember_note("Owner asked Doggie to remember them personally.")
