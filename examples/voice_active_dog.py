from pidog.voice_assistant import VoiceAssistant

from pidog.pidog import Pidog
from pidog.dual_touch import TouchStyle
from pidog.action_flow import ActionFlow, ActionStatus, Posetures
from dog_abilities import AbilitiesMixin
from memory_store import DoggieMemory
from owner_voice import OwnerVoice

import time
import threading
import random
import json
import re
import subprocess
import socket
import os
import hmac
import html
import secrets
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Robot name
NAME = "doggie"

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
ANSWER_ON_WAKE = "yes im here"

# Welcome message
WELCOME = f"Hi, I'm {NAME}. Wake me up with: " + ", ".join(WAKE_WORD)

# Set instructions
INSTRUCTIONS = """
You are a Raspberry Pi-based robotic dog developed by your owner matthew, named doggie (pronounced "dog ie"). You possess powerful AI capabilities similar to JARVIS from Iron Man. You can have conversations with people and perform actions based on the context of the conversation.

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
["forward", "backward", "lie", "stand", "sit", "bark", "bark harder", "pant", "howling", "wag tail", "push up", "scratch", "handshake", "high five", "lick hand", "shake head", "relax neck", "nod", "think", "recall", "head down", "fluster", "surprise"]

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
    CAMERA_BRIGHTEN_TARGET = 138
    CAMERA_BRIGHTEN_MAX_GAIN = 6.0
    # The Robot HAT capture path is already at its 25 dB hardware maximum.
    # This modest software boost improves normal-distance speech recognition.
    MIC_DIGITAL_GAIN = 1.45
    # Run the CPU pose/hand landmark models at a modest cadence. The IMX500
    # still performs the main object detection on-camera every frame.
    HUMAN_FEATURE_INTERVAL_S = 0.80
    TORSO_PERSON_CONFIDENCE = 0.90
    COMMAND_LISTEN_SILENCE = 1.35
    # Allow two more seconds for a complete command after the wake response.
    COMMAND_LISTEN_MAX_SECONDS = 10.0
    # This is a one-shot conversational window, not an indefinite listen.
    # Four seconds gives a person time to begin a natural reply after TTS.
    FOLLOW_UP_LISTEN_SECONDS = 4.0
    DIRECT_ACTION_PATTERNS = {
        # These are intentionally local, stationary actions.  They remain
        # available when the cloud model cannot be reached, but walking and
        # turning always require the online decision path and supervision.
        "stop": ("stop", "stop it", "be still", "freeze"),
        "sit": ("sit", "sit down", "sit up"),
        "stand": ("stand", "stand up"),
        "lie": ("lie down", "lay down", "lie"),
        "learn my face": ("learn my face",),
        "learn my voice": ("learn my voice", "learn my voice print"),
        "track person": ("track person", "follow the person", "follow me"),
        "track object": ("track object", "track objects", "follow an object"),
        "bark harder": ("bark harder",),
        "bark": ("bark",),
        "pant": ("pant",),
        "howling": ("howl", "howling"),
        "wag tail": ("wag tail", "wag your tail"),
        "shake head": ("shake head", "shake your head"),
        # Disabled after a reported hardware stall during the stretch pose.
        "nod": ("nod",),
        "head down": ("head down",),
        "safe shutdown": ("prepare shutdown", "safe shutdown", "shut down doggie"),
        "fart": (
            "take a poop right here",
            "take a poop",
            "poop right here",
            "fart",
        ),
    }

    VOICE_ACTIONS = ["bark", "bark harder", "pant",  "howling"]
    WAKE_SYNONYMS = {
        # Vosk's small local model has repeatedly heard Doggie as these
        # near-sounding words in the garage.  They are accepted only as part
        # of the wake phrase (or as the one-word name fallback below).
        "doggie": {"doggie", "doggy", "dog", "dougie", "duggy",
                   "dodgy", "dummy", "derby", "doug", "jodie", "jody",
                   "daddy", "doge", "dawg", "doogie", "dougy", "dodge",
                   "dodgey", "doggiee"},
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
    STATUS_REPORT_PATTERNS = (
        "network status",
        "wifi status",
        "wi fi status",
        "internet status",
        "connection status",
        "what network",
        "which network",
        "what is your ip address",
        "what's your ip address",
        "what is your ip",
        "what's your ip",
        "tell me your ip address",
        "battery status",
        "battery level",
        "how much battery",
        "power status",
        "status report",
        "doggie status",
    )
    WIFI_SCAN_PATTERNS = (
        "scan wifi",
        "scan wi fi",
        "scan for wifi",
        "scan for wi fi",
        "list wifi",
        "list wi fi",
        "list hotspots",
        "list hot spots",
        "available wifi",
        "available wi fi",
        "available hotspots",
        "available hot spots",
        "find wifi",
        "find wi fi",
        "find hotspots",
        "find hot spots",
        "what wifi networks",
        "what wi fi networks",
        "what hotspots",
        "what hot spots",
        "what networks are available",
        "which networks are available",
        "show available networks",
        "can you connect to any other networks",
        "can you connect to another network",
        "connect to another network",
        "other wifi networks",
        "other wi fi networks",
    )
    # The web panel deliberately exposes only stationary, low-risk actions.
    # Any walking or free-form AI command still has to come through voice.
    WEB_COMMANDS = {
        "listen": "__web_listen_once__",
        "stop": "stop",
        "sit": "sit",
        "stand": "stand",
        "lie down": "lie down",
        "bark": "bark",
        "bark harder": "bark harder",
        "pant": "pant",
        "howl": "howl",
        "wag tail": "wag tail",
        "shake head": "shake head",
        # Disabled until the pose is validated with a timeout/recovery guard.
        "nod": "nod",
        "head down": "head down",
        "prepare shutdown": "safe shutdown",
        "status report": "status report",
    }

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
                from picamera2.devices import IMX500
                model_path = ("/usr/share/imx500-models/"
                              "imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk")
                # Must precede Picamera2 construction: it loads the neural
                # network into the AI Camera's on-sensor accelerator.
                ai_camera = IMX500(model_path)
                intrinsics = ai_camera.network_intrinsics
                if intrinsics is None or intrinsics.task != "object detection":
                    raise RuntimeError("AI Camera model is not object detection")
                intrinsics.update_with_defaults()
                cam = Picamera2(ai_camera.camera_num)
                cam.configure(cam.create_preview_configuration(
                    main={"size": (960, 720)}, buffer_count=8,
                    controls={"FrameRate": intrinsics.inference_rate}))
                ai_camera.show_network_fw_progress_bar()
                cam.start()
                # garage is dim: default AE tops out at 33ms exposure (30fps
                # timing) and frames came out very dark. Give AE more room,
                # bias it brighter, and keep AWB on for face learning.
                cam.set_controls({
                    "AeEnable": True,
                    "AwbEnable": True,
                    "ExposureValue": 2.5,
                    "FrameDurationLimits": (33333, 100000),
                })
                _pre["cam"] = cam
                _pre["ai_camera"] = ai_camera
                _pre["ai_labels"] = intrinsics.labels or []
            except Exception as e:
                # Vision is optional. A missing camera must not prevent the
                # speech-and-motion assistant from starting.
                print(f"camera unavailable; starting without vision: {e}")

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
        else:
            # Do not let the base class retry an unavailable camera.
            kwargs["with_image"] = False
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
        self.ai_camera = _pre.get("ai_camera")
        self.ai_labels = _pre.get("ai_labels", [])
        self.ai_track_target = "person"
        self._last_ai_detections = []
        self._human_features = {"hands": [], "arms": [], "torso": None,
                                "torso_kind": None, "timestamp": 0.0}
        self._human_pose = None
        self._hand_tracker = None
        self._last_human_feature_at = 0.0
        # Tracking state is deliberately separate from detection state. A
        # detector can miss a frame when somebody turns or the exposure
        # changes; a brief grace period avoids jitter, then a head-only scan
        # reacquires the target without following stale AI-camera results.
        self._tracked_at = 0.0
        self._search_yaw = 0.0
        self._search_direction = 1.0
        self._last_search_at = 0.0
        self._latest_faces = []
        self._latest_faces_at = 0.0
        self._latest_person_target = None
        self._person_lock_center = None
        self._watch_failure_times = []
        self._last_stt_audio = b""
        self._last_stt_sample_rate = 16000
        self.voice_identity = OwnerVoice()
        self._web_commands = queue.Queue(maxsize=10)
        self._web_server = None
        self._web_server_thread = None
        self._web_sessions = {}
        self._wake_prefix_until = 0.0
        self._speech_active = False
        self._queued_follow_up = None
        self._wifi_scan_choices = []
        self._wifi_scan_at = 0.0
        self._shutdown_status = {"state": "idle", "detail": ""}
        self.add_trigger(self.trigger_web_command)
        self.add_trigger(self.trigger_follow_up)

        # Keep visual/head motion quiet while TTS is speaking. This wrapper
        # also covers messages spoken by individual abilities.
        original_tts_say = self.tts.say
        def quiet_tts_say(*args, **kwargs):
            self._speech_active = True
            try:
                return original_tts_say(*args, **kwargs)
            finally:
                self._speech_active = False
        self.tts.say = quiet_tts_say

        # Wake word fix: the library requires the transcription to EXACTLY
        # equal a wake word, so any background noise or extra words defeats
        # it. Match the wake word anywhere in the utterance instead, and log
        # what was heard on a normal line so it is readable in the journal.
        import types
        def _heard_wake_word_substring(stt_self, print_callback=None):
            try:
                result = stt_self.listen(stream=False)
            except _sd.PortAudioError as exc:
                # Keep a temporary device-busy race from killing the wake
                # thread. It will retry after the one-shot listener exits.
                print(f"wake microphone temporarily unavailable: {exc}")
                _time.sleep(0.25)
                return False
            if result is None:
                return False
            self._remember_sound_direction()
            hit = self._is_wake_phrase(result, stt_self.wake_words)
            # The local recognizer sometimes finalizes "hey" before it hears
            # the name. Keep a brief prefix window so its next audio chunk can
            # complete the phrase instead of making Matt repeat it.
            if self._is_wake_prefix(result):
                self._wake_prefix_until = _time.monotonic() + 5.0
            elif (_time.monotonic() < self._wake_prefix_until
                  and self._normalize_phrase(result).split() == ["doggie"]):
                hit = True
            if hit:
                self._wake_prefix_until = 0.0
                self.memory.note_wake_phrase(result)
            print(f"heard: {result}" + ("  [WAKE]" if hit else ""))
            return hit
        self.stt.heard_wake_word = types.MethodType(_heard_wake_word_substring, self.stt)

        # Snappier end-of-speech detection: the stock code waits for Kaldi's
        # endpointer, which is slow and never fires while background noise
        # keeps "speech" going. Instead, finalize once the partial
        # transcription stops changing, with a hard cap as a backstop.
        import audioop as _audioop
        import json as _json
        import queue as _queue
        import time as _time
        import sounddevice as _sd
        self._sounddevice = _sd

        def _remember_audio(chunks, sample_rate):
            self._last_stt_audio = b"".join(chunks)
            self._last_stt_sample_rate = int(sample_rate or self.stt._samplerate)

        def _amplified_callback(callback):
            def amplified(indata, frames, time_info, status):
                try:
                    indata = _audioop.mul(bytes(indata), 2, self.MIC_DIGITAL_GAIN)
                except Exception as exc:
                    print(f"microphone gain warning: {exc}")
                callback(indata, frames, time_info, status)
            return amplified

        def _snappy_listen_streaming(stt_self, q, device=None, samplerate=None, callback=None,
                                     stable_silence=0.7, max_utterance=6.0):
            stable_silence = getattr(self, "_listen_silence",
                                     self.COMMAND_LISTEN_SILENCE)
            max_utterance = getattr(self, "_listen_max_seconds",
                                    self.COMMAND_LISTEN_MAX_SECONDS)
            with _sd.RawInputStream(samplerate=samplerate, blocksize=1024, device=device,
                                    dtype="int16", channels=1,
                                    callback=_amplified_callback(callback)):
                audio_chunks = []
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
                        _remember_audio(audio_chunks, samplerate)
                        yield {"done": True, "partial": "", "final": text}
                        return
                    try:
                        data = q.get(timeout=0.2)
                    except _queue.Empty:
                        continue
                    audio_chunks.append(data)
                    if stt_self.recognizer.AcceptWaveform(data):
                        text = _json.loads(stt_self.recognizer.Result()).get("text", "")
                        if text == "":
                            continue
                        _remember_audio(audio_chunks, samplerate)
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
                                dtype="int16", channels=1,
                                callback=_amplified_callback(callback)):
                audio_chunks = []
                last_partial = ""
                last_change = None
                start = _time.time()
                while True:
                    if stt_self.stop_listening_event.is_set():
                        return None
                    now = _time.time()
                    # Do not cut off immediately after a standalone wake
                    # prefix. Vosk often emits "hey" first and needs another
                    # fraction of a second to add "doggie" to the result.
                    prefix_grace = (1.15 if self._is_wake_prefix(last_partial)
                                    else stable_silence)
                    if ((last_change is not None and now - last_change > prefix_grace)
                            or (now - start > max_listen)):
                        text = _json.loads(stt_self.recognizer.FinalResult()).get("text", "").strip()
                        _remember_audio(audio_chunks, samplerate)
                        return text if text else None
                    try:
                        data = q.get(timeout=0.2)
                    except _queue.Empty:
                        continue
                    audio_chunks.append(data)
                    if stt_self.recognizer.AcceptWaveform(data):
                        text = _json.loads(stt_self.recognizer.Result()).get("text", "")
                        if text == "":
                            continue
                        _remember_audio(audio_chunks, samplerate)
                        return text.strip()
                    partial = _json.loads(stt_self.recognizer.PartialResult()).get("partial", "")
                    if partial and not partial.isspace() and partial != last_partial:
                        last_partial = partial
                        last_change = _time.time()
                        # The wake listener used to wait for Vosk's endpoint
                        # even after it had already recognized "hey doggie".
                        # Return the partial immediately, then reset so the
                        # following command starts with a clean recognizer.
                        if self._is_wake_phrase(partial, stt_self.wake_words):
                            _remember_audio(audio_chunks, samplerate)
                            stt_self.recognizer.Reset()
                            return partial

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
        self.auto_tracking = True
        self._setup_balance()
        self._start_camera_stream()
        self._setup_abilities()
        # Default to local face tracking now that the head limiter permits
        # yaw only. Guard mode still takes exclusive control as needed.
        self.start_watch()

    def init_pidog(self):
        try:
            self.dog = Pidog()
            if os.environ.get("DOGGIE_HEAD_MOTION_ENABLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
                # The camera-board power connector limits rear/up travel. Keep
                # yaw tracking. Extra upward pitch is allowed only while
                # sitting with a confirmed face lock; standing and lying
                # remain at their known-safe forward pitch.
                original_head_move = self.dog.head_move
                original_head_move_raw = self.dog.head_move_raw
                # Sitting changes the body/head geometry. Shift both known
                # safe neutral positions. Stand and lay can safely rest an
                # additional 5 degrees back/up: -10 standing/lying, -30 sitting.
                rest_pitch = -10
                sit_pitch = -30
                downward_pitch_limit = -35
                sit_person_upward_pitch = 20
                sit_face_upward_pitch = 25
                self.dog.head_stop()

                self.action_flow = ActionFlow(self.dog)
                self.action_flow.SIT_HEAD_PITCH = sit_pitch
                self.action_flow.STAND_HEAD_PITCH = rest_pitch

                def current_safe_pitch():
                    return (sit_pitch if self.action_flow.posture == Posetures.SIT
                            else rest_pitch)

                def upward_pitch_limit():
                    """Let a seated person search become slightly higher on face lock."""
                    if (self.action_flow.posture == Posetures.SIT
                            and getattr(self, "_face_tracking_locked", False)):
                        return sit_face_upward_pitch
                    if (self.action_flow.posture == Posetures.SIT
                            and getattr(self, "_person_tracking_locked", False)):
                        return sit_person_upward_pitch
                    return 0

                def set_safe_forward_head(_pitch=None):
                    safe_pitch = current_safe_pitch()
                    self.action_flow.head_pitch_init = safe_pitch
                    original_head_move([[0, 0, 0]],
                                       pitch_comp=safe_pitch,
                                       immediately=True, speed=30)

                self.action_flow.set_head_pitch_init = set_safe_forward_head
                set_safe_forward_head()

                def limited_head_move(target_yrps, roll_comp=0, pitch_comp=0,
                                      immediately=True, speed=50):
                    # In PiDog coordinates positive target pitch is upward.
                    # Looking down is safe in every posture. Stand/lie have
                    # no extra rear/up range; sitting gets a moderate window
                    # after a confirmed person or face lock.
                    safe_targets = [[target[0], 0,
                                     max(downward_pitch_limit,
                                         min(upward_pitch_limit(), target[2]))]
                                    for target in target_yrps]
                    original_head_move(safe_targets,
                                       pitch_comp=current_safe_pitch(),
                                       immediately=immediately, speed=speed)

                def limited_head_move_raw(target_angles, immediately=True,
                                          speed=50):
                    safe_pitch = current_safe_pitch()
                    safe_targets = [[target[0], 0,
                                     max(safe_pitch + downward_pitch_limit,
                                         min(safe_pitch + upward_pitch_limit(),
                                             target[2]))]
                                    for target in target_angles]
                    original_head_move_raw(safe_targets, immediately=immediately,
                                          speed=speed)

                self.dog.head_move = limited_head_move
                self.dog.head_move_raw = limited_head_move_raw

                # ActionFlow normally suppresses a consecutive identical
                # action.  Always restore the known-safe passive pose after
                # any requested posture so "sit up" reliably restores the
                # safe forward pose even when Doggie was already sitting.
                original_change_posture = self.action_flow.change_poseture

                def change_posture_with_safe_head(posture):
                    original_change_posture(posture)
                    set_safe_forward_head()

                self.action_flow.change_poseture = change_posture_with_safe_head
                print("head safety limiter enabled: down=35 degrees in every posture; "
                      "seated person up=20, seated face up=25 degrees; "
                      "stand/lie stay forward; rest=-10, sit=-30")
            else:
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

    def trigger_follow_up(self):
        """Feed a just-heard answer into the next assistant round."""
        message = self._queued_follow_up
        if not message:
            return False, False, ""
        self._queued_follow_up = None
        print("follow-up: heard a reply")
        return True, False, message

    def before_think(self, text):
        self.dog.rgb_strip.set_mode('listen', 'yellow', 1)
        if self._is_visual_query(text):
            self.start_visual_survey()

    def on_start(self):
        # VoiceAssistant speaks ``self.welcome`` immediately after this hook.
        # Build it from local-only sources so startup is useful offline too.
        self.welcome = self._build_startup_announcement()
        self.action_flow.start()
        self._start_web_control_server()
        self.dog.rgb_strip.close()
        # self.action_flow.change_poseture(Posetures.SIT)  # disabled so lie/stay-down can hold

    def on_wake(self):
        if len(self.answer_on_wake) > 0:
            self.dog.rgb_strip.set_mode('breath', 'pink', 1)
        # Perk up gently—the microphone needs a quiet moment after wake-up.
        self.head_excite(6.0)

    def _listen_for_follow_up(self):
        """Briefly listen after Doggie explicitly asks the user a question."""
        response = getattr(self, "_last_spoken_response", "").strip()
        if not response.endswith("?"):
            return
        print("follow-up: listening for up to 4 seconds")
        self._listen_silence = 0.75
        self._listen_max_seconds = self.FOLLOW_UP_LISTEN_SECONDS
        try:
            reply = self.listen()
        finally:
            self._listen_silence = self.COMMAND_LISTEN_SILENCE
            self._listen_max_seconds = self.COMMAND_LISTEN_MAX_SECONDS
        if reply:
            self._queued_follow_up = reply
        else:
            # The follow-up window timed out. Clear the cyan listening state
            # before returning to normal wake-word monitoring.
            self.dog.rgb_strip.close()
            print("follow-up: no reply; returned to wake mode")

    def on_heard(self, text):
        self.action_flow.set_status(ActionStatus.THINK)
        self._last_user_text = text or ""
        self._last_visual_query = self._is_visual_query(self._last_user_text)
        self._last_identity_query = self._is_identity_query(self._last_user_text)
        self.memory.note_interaction(self._last_user_text)
        self._extract_owner_cues(self._last_user_text)

    def parse_response(self, text):
        # `ACTIONS:` is a private control channel for Doggie.  Models do not
        # always preserve the exact ``ACTIONS: <value>`` spacing, so recognize
        # the directive case-insensitively and never pass it to TTS.
        raw = (text or "").strip()
        match = re.search(r"(?im)^\s*actions?\s*:\s*(.*)$", raw)
        if match:
            response_text = raw[:match.start()].strip()
            action_text = match.group(1).strip()
            actions = [part.strip() for part in action_text.split(",") if part.strip()]
            if not actions:
                actions = ["stop"]
        else:
            response_text = raw
            actions = ["stop"]

        # Models occasionally echo the response placeholder or an additional
        # control line.  Neither is meant for the user to hear.
        junk = '"*\'` '
        lines = [
            line for line in response_text.splitlines()
            if line.strip(junk).upper() not in ("RESPONSE_TEXT", "RESPONSE TEXT")
            and not re.match(r"^\s*actions?\s*:", line, flags=re.IGNORECASE)
        ]
        response_text = "\n".join(lines).strip()
        self._last_spoken_response = response_text
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
        self._resume_tracking_when_idle()
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
        ("twist body", 1), ("feet shake", 1),
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
        self._resume_tracking_when_idle()
        # back to sit
        # self.action_flow.change_poseture(Posetures.SIT)  # disabled so lie/stay-down can hold
        # close rgb strip
        self.dog.rgb_strip.close()
        self._listen_for_follow_up()


    # -- IMU balance mode ---------------------------------------------------
    # Same control loop as examples/10_balance.py: PID on the IMU keeps the
    # body level. While the loop owns the leg servos, no other action may
    # move them -- guarded_run enforces that.
    BALANCE_STAND_COORDS = [[-15, 95], [-15, 95], [5, 90], [5, 90]]
    BALANCE_POSE = {'x': 0, 'y': 0, 'z': 80}
    IDLE_ACTIONS = ('waiting', 'feet_left_right')

    MODE_ACTIONS = ("balance on", "balance off", "watch me", "stop watching",
                    "track person", "track object", "guard on", "guard off")

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
            "function": lambda flow: self.stop_watch(manual=True),
        }
        self.action_flow.OPERATIONS["track person"] = {
            "function": lambda flow: self.start_ai_tracking("person"),
            "poseture": Posetures.SIT,
        }
        self.action_flow.OPERATIONS["track object"] = {
            "function": lambda flow: self.start_ai_tracking("object"),
            "poseture": Posetures.SIT,
        }
        self.action_flow.OPERATIONS["safe shutdown"] = {
            "function": lambda flow: self._safe_shutdown_posture(),
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
            "track person": "watch", "track object": "watch",
                        "guard on": "guard"}
            if action in starters:
                self.stop_all_modes(keep=starters[action])
            orig_run(action)
        self.action_flow.run = guarded_run

    def _safe_shutdown_posture(self) -> None:
        """Lower rear legs first, then front legs, using the live controller.

        PiDog's standard servos do not report measured joint position.  The
        stage verification therefore confirms that the live controller drained
        its motion queue and reached its commanded rear-leg target before the
        front-leg stage begins.  A fresh ``Pidog`` instance is deliberately
        avoided: its initialization pose would command all legs at once.
        """
        rear_speed = 22
        front_speed = 22
        lie = list(self.dog.actions_dict["lie"][0][0])
        self._shutdown_status = {"state": "lowering_rear", "detail": ""}
        try:
            self.stop_all_modes()
            self.dog.legs_stop()
            # Leg order is front-left/right (0..3), then rear-left/right
            # (4..7). Preserve the front legs while the rear settles.
            current = list(self.dog.legs.servo_positions)
            rear_target = current[:4] + lie[4:]
            self.dog.legs_move([rear_target], immediately=True, speed=rear_speed)
            self.dog.wait_legs_done()
            reached_rear = all(
                abs(actual - target) < 0.5
                for actual, target in zip(self.dog.legs.servo_positions[4:], lie[4:])
            )
            if not reached_rear:
                raise RuntimeError("rear-leg command did not reach its target")

            self._shutdown_status = {"state": "lowering_front", "detail": "rear verified"}
            self.dog.legs_move([lie], immediately=True, speed=front_speed)
            self.dog.wait_legs_done()
            reached_lie = all(
                abs(actual - target) < 0.5
                for actual, target in zip(self.dog.legs.servo_positions, lie)
            )
            if not reached_lie:
                raise RuntimeError("front-leg command did not reach its target")
            self.action_flow.posture = Posetures.LIE
            self._shutdown_status = {"state": "ready", "detail": "rear then front lie complete"}
            print("safe shutdown posture: rear verified, front lowered, ready")
        except Exception as exc:
            self._shutdown_status = {"state": "failed", "detail": str(exc)}
            print(f"safe shutdown posture failed: {exc}")

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
        self.auto_tracking = True
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

    def stop_watch(self, manual=False):
        if manual:
            self.auto_tracking = False
        if not self.watch_on:
            return
        self.watch_on = False
        if self.watch_thread is not None:
            self.watch_thread.join(timeout=3)
            self.watch_thread = None
        print("watch mode: OFF")

    def _resume_tracking_when_idle(self):
        """Ordinary posture/actions must not permanently disable tracking."""
        if (getattr(self, "auto_tracking", True)
                and not self.watch_on
                and not self.balance_on
                and not getattr(self, "guard_on", False)):
            self.start_watch()

    def start_ai_tracking(self, target):
        """Select an on-camera AI class without enabling unsafe walking."""
        if self.ai_camera is None:
            print("AI tracking unavailable: AI Camera model did not start")
            return
        self.ai_track_target = target
        self.start_watch()
        print(f"AI tracking: {target}")

    def _get_ai_detections(self):
        """Read IMX500 results produced on the camera, not a cloud service."""
        if self.ai_camera is None:
            return []
        try:
            metadata = self.picam2.capture_metadata()
            outputs = self.ai_camera.get_outputs(metadata, add_batch=True)
            if outputs is None:
                # There is no fresh inference result yet.  Do not report old
                # boxes as a live target: that prevents the search path below
                # from reacquiring someone who has moved out of frame.
                return []
            boxes, scores, classes = outputs[0][0], outputs[1][0], outputs[2][0]
            detections = []
            for box, score, category in zip(boxes, scores, classes):
                if float(score) < 0.50:
                    continue
                category = int(category)
                label = (self.ai_labels[category] if category < len(self.ai_labels)
                         else f"class {category}")
                x, y, w, h = self.ai_camera.convert_inference_coords(
                    box, metadata, self.picam2)
                detections.append({"label": label.lower(), "score": float(score),
                                   "box": (int(x), int(y), int(w), int(h))})
            self._last_ai_detections = detections
            return detections
        except Exception as exc:
            print(f"AI Camera inference warning: {exc}")
            return self._last_ai_detections

    def _detect_human_features(self, frame, cv2):
        """Find torso, arm, and hand landmarks with lightweight local models."""
        now = time.monotonic()
        if now - self._last_human_feature_at < self.HUMAN_FEATURE_INTERVAL_S:
            return self._human_features
        self._last_human_feature_at = now
        try:
            import mediapipe as mp

            if self._human_pose is None:
                self._human_pose = mp.solutions.pose.Pose(
                    static_image_mode=False, model_complexity=0,
                    enable_segmentation=False, min_detection_confidence=0.55,
                    min_tracking_confidence=0.55,
                )
                self._hand_tracker = mp.solutions.hands.Hands(
                    static_image_mode=False, max_num_hands=2, model_complexity=0,
                    min_detection_confidence=0.55, min_tracking_confidence=0.55,
                )

            height, width = frame.shape[:2]
            # 320x240 is sufficient for landmarks and keeps this auxiliary
            # CPU work from competing with the AI-camera detector.
            small = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            pose_result = self._human_pose.process(rgb)
            hand_result = self._hand_tracker.process(rgb)
            features = {"hands": [], "arms": [], "torso": None,
                        "torso_kind": None, "timestamp": now}

            if pose_result.pose_landmarks:
                landmarks = pose_result.pose_landmarks.landmark

                def point(index, minimum=0.45):
                    landmark = landmarks[index]
                    if landmark.visibility < minimum:
                        return None
                    return int(landmark.x * width), int(landmark.y * height)

                # MediaPipe Pose: shoulders 11/12, elbows 13/14, wrists 15/16,
                # hips 23/24. Hips disappear when the camera sees only an
                # upper body, so recognize that as a torso too: two shoulders
                # plus at least one elbow or hip is strong human-shape evidence
                # inside the AI camera's person box.
                left_shoulder, right_shoulder = point(11, 0.45), point(12, 0.45)
                left_elbow, right_elbow = point(13), point(14)
                left_hip, right_hip = point(23), point(24)
                upper_body_points = [left_shoulder, right_shoulder]
                upper_body_points += [item for item in
                                      (left_elbow, right_elbow, left_hip, right_hip)
                                      if item]
                if (left_shoulder and right_shoulder
                        and len(upper_body_points) >= 3):
                    xs = [item[0] for item in upper_body_points]
                    ys = [item[1] for item in upper_body_points]
                    padding = max(10, int((max(xs) - min(xs)) * 0.15))
                    features["torso"] = (
                        max(0, min(xs) - padding), max(0, min(ys) - padding),
                        min(width - max(0, min(xs) - padding), max(xs) - min(xs) + 2 * padding),
                        min(height - max(0, min(ys) - padding), max(ys) - min(ys) + 2 * padding),
                    )
                    features["torso_kind"] = (
                        "full torso" if left_hip and right_hip else "upper torso"
                    )

                for name, shoulder, elbow, wrist in (
                    ("left arm", point(11), point(13), point(15)),
                    ("right arm", point(12), point(14), point(16)),
                ):
                    points = [item for item in (shoulder, elbow, wrist) if item]
                    if len(points) >= 2:
                        features["arms"].append({"label": name, "points": points})

            if hand_result.multi_hand_landmarks:
                for landmarks in hand_result.multi_hand_landmarks:
                    xs = [int(item.x * width) for item in landmarks.landmark]
                    ys = [int(item.y * height) for item in landmarks.landmark]
                    features["hands"].append((min(xs), min(ys),
                                              max(xs) - min(xs), max(ys) - min(ys)))
            self._human_features = features
        except Exception as exc:
            print(f"human landmark warning: {exc}")
        return self._human_features

    @staticmethod
    def _box_from_face(face):
        """Normalize Haar (x,y,w,h) and YuNet face rows to x,y,w,h."""
        return tuple(int(v) for v in face[:4])

    @staticmethod
    def _face_is_inside(face_box, person_box):
        fx, fy, fw, fh = face_box
        px, py, pw, ph = person_box
        cx, cy = fx + fw / 2.0, fy + fh / 2.0
        return px <= cx <= px + pw and py <= cy <= py + ph

    @staticmethod
    def _person_regions(person_box, include_torso=True):
        """Derive a head region and, only when needed, a torso fallback."""
        x, y, w, h = person_box
        head = (x + int(w * 0.16), y, int(w * 0.68), int(h * 0.34))
        torso = None
        if include_torso:
            torso = (x + int(w * 0.10), y + int(h * 0.28),
                     int(w * 0.80), int(h * 0.42))
        return head, torso

    @staticmethod
    def _box_center(box):
        x, y, w, h = box
        return x + w / 2.0, y + h / 2.0

    def _choose_person_target(self, detections, faces):
        """Lock one face/torso-confirmed person and reject unverified boxes.

        The IMX500 SSD model is useful for finding a broad human-shaped area,
        but items such as backpacks can occasionally receive its ``person``
        label. A face or the pose model's four-anchor torso inside that area is
        required before Doggie calls it a person or follows it. Face-only
        detection remains usable so a close, cropped face is never lost just
        because the full-body model misses.
        """
        people = [d for d in detections if d["label"] == "person"]
        human_features = self._human_features
        body_torso = (human_features.get("torso")
                      if time.monotonic() - human_features.get("timestamp", 0.0) < 1.0
                      else None)
        if not people:
            if faces:
                face = max((self._box_from_face(item) for item in faces),
                           key=lambda box: box[2] * box[3])
                # A face-only result can still be aimed at, but is visibly
                # marked as such until the AI model finds the full person.
                return {"person": None, "head": face, "torso": None,
                        "face": face, "aim": face, "confidence": 1.0}
            if body_torso:
                # Shoulders plus hips are present even if SSD has momentarily
                # missed the wider person box. This is an operational 90%
                # confidence signal, not a calibrated biometric identity.
                return {"person": body_torso, "head": None, "torso": body_torso,
                        "face": None, "aim": body_torso,
                        "confidence": self.TORSO_PERSON_CONFIDENCE}
            return None

        confirmed = []
        for detection in people:
            person_box = detection["box"]
            matching_faces = [self._box_from_face(face) for face in faces
                              if self._face_is_inside(
                                  self._box_from_face(face), person_box)]
            torso_matches = bool(body_torso and self._face_is_inside(body_torso, person_box))
            if matching_faces or torso_matches:
                # The camera stream reads this same fresh result list, so it
                # can distinguish the model's tentative box from a verified
                # person without performing a second inference.
                detection["person_confirmed"] = True
                detection["person_confidence"] = (
                    1.0 if matching_faces else self.TORSO_PERSON_CONFIDENCE
                )
                confirmed.append((person_box, matching_faces, body_torso if torso_matches else None))

        if not confirmed:
            # Keep raw model boxes visible as *possible* people for diagnosis,
            # but never follow one until the face detector corroborates it.
            return None

        def rank(item):
            person = item[0]
            if self._person_lock_center is None:
                return person[2] * person[3]
            cx, cy = self._box_center(person)
            lx, ly = self._person_lock_center
            # Prefer continuity over a newly entering, larger bystander.
            return -((cx - lx) ** 2 + (cy - ly) ** 2)

        person, matching_faces, confirmed_torso = max(confirmed, key=rank)
        face = max(matching_faces, key=lambda box: box[2] * box[3]) if matching_faces else None
        # Face lock is the compact, precise target. Only retain the broader
        # torso region after a face miss, where it helps reacquire the person.
        head, torso = self._person_regions(person, include_torso=face is None)
        if confirmed_torso is not None:
            torso = confirmed_torso
        self._person_lock_center = self._box_center(person)
        # Face lock needs no torso tracking. On a face miss, head then torso
        # provide a stable path back to the same person.
        return {"person": person, "head": head, "torso": torso,
                "face": face, "aim": face or head or torso,
                "confidence": 1.0 if face else self.TORSO_PERSON_CONFIDENCE}

    def _choose_tracking_box(self, detections, faces):
        """Return the finest stable target appropriate for the requested mode."""
        if self.ai_track_target == "object":
            candidates = [d for d in detections if d["label"] != "person"]
            return (max(candidates, key=lambda d: d["box"][2] * d["box"][3])["box"]
                    if candidates else None)
        return self._choose_person_target(detections, faces)

    def _search_for_target(self, yaw, pitch):
        """Sweep the head slowly when vision loses its target.

        This is intentionally head-only: reacquisition must never cause the
        dog to walk after a person/object disappears.
        """
        now = time.monotonic()
        if now - self._last_search_at < 0.30:
            return yaw, pitch
        self._last_search_at = now
        self._search_yaw += 8.0 * self._search_direction
        if abs(self._search_yaw) >= 78:
            self._search_yaw = max(-78, min(78, self._search_yaw))
            self._search_direction *= -1.0
        self.dog.head_move([[self._search_yaw, 0, pitch]], pitch_comp=-35,
                           immediately=True, speed=55)
        return self._search_yaw, pitch

    def _watch_loop(self):
        import cv2
        yaw = 0.0
        pitch = 0.0
        try:
            while self.watch_on:
                if (getattr(self, "_cmd_listening", False)
                        or getattr(self, "_speech_active", False)):
                    # Microphone clarity and natural speech matter more than
                    # camera centering during a conversation turn.
                    time.sleep(0.08)
                    continue
                frame = self.picam2.capture_array()
                if frame.ndim == 3 and frame.shape[2] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                frame = self._brighten(frame, cv2)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.detect_faces(cv2, frame, gray)
                self._latest_faces = [self._box_from_face(face) for face in faces]
                self._latest_faces_at = time.monotonic()
                self._detect_human_features(frame, cv2)
                detections = self._get_ai_detections()
                target = self._choose_tracking_box(detections, faces)
                if self.ai_track_target == "person":
                    self._latest_person_target = target
                    target_box = target["aim"] if target else None
                    # Recognition follows the associated face, not simply the
                    # largest face anywhere in frame, so a bystander cannot
                    # overwrite the active person's identity status.
                    if target and target["face"] is not None:
                        for raw_face in faces:
                            if self._box_from_face(raw_face) == target["face"]:
                                try:
                                    target["identity"] = self.remember_visible_face(
                                        cv2, frame, gray, raw_face)
                                except Exception as exc:
                                    # Identity is an enhancement, never a
                                    # reason to lose the person tracker.
                                    print(f"face recognition warning: {exc}")
                                    target["identity"] = "unavailable"
                                break
                else:
                    self._latest_person_target = None
                    target_box = target
                if target_box is None:
                    self._face_tracking_locked = False
                    self._person_tracking_locked = False
                    # A short grace period makes one dropped frame invisible;
                    # after that, sweep until either the AI person/object box
                    # or the nested face box is detected again.
                    if time.monotonic() - self._tracked_at > 0.35:
                        yaw, pitch = self._search_for_target(yaw, pitch)
                    time.sleep(0.05)
                    continue
                x, y, w, h = target_box
                person_locked = bool(self.ai_track_target == "person" and target)
                face_locked = bool(person_locked and target["face"] is not None)
                self._person_tracking_locked = person_locked
                self._face_tracking_locked = face_locked
                self._tracked_at = time.monotonic()
                self._search_yaw = yaw
                frame_center_x = frame.shape[1] / 2.0
                frame_center_y = frame.shape[0] / 2.0
                ex = (x + w / 2.0) - frame_center_x
                ey = (y + h / 2.0) - frame_center_y
                # Rate-limit each correction and use lower servo speed. This
                # turns the former snap-to-box behavior into a smooth chase.
                if abs(ex) > 15:
                    yaw += max(-2.0, min(2.0, -ex * 0.020))
                    yaw = max(-80, min(80, yaw))
                if abs(ey) > 25:
                    pitch += max(-0.75, min(0.75, -ey * 0.015))
                    upward_limit = (25 if face_locked
                                    and self.action_flow.posture == Posetures.SIT
                                    else 20 if person_locked
                                    and self.action_flow.posture == Posetures.SIT
                                    else 0)
                    pitch = max(-35, min(upward_limit, pitch))
                self.dog.head_move([[yaw, 0, pitch]], pitch_comp=-35,
                                   immediately=True, speed=42)
                time.sleep(0.08)
        except Exception as e:
            print(f"watch loop error: {e}")
            self.watch_on = False
            now = time.monotonic()
            self._watch_failure_times = [t for t in self._watch_failure_times
                                         if now - t < 60.0]
            self._watch_failure_times.append(now)
            if len(self._watch_failure_times) >= 3:
                # A thread failure does not end the Python service, so let
                # systemd's existing Restart=always policy rebuild the camera
                # and all tracking state after repeated failures.
                print("watch loop failed repeatedly; restarting pidog-gpt service")
                os._exit(1)
            # One bad frame or recognition result should recover locally and
            # retain the rest of the assistant session.
            delay = float(len(self._watch_failure_times))
            print(f"watch mode: retrying after {delay:.0f}s")
            time.sleep(delay)
            if (getattr(self, "auto_tracking", True)
                    and not self.balance_on
                    and not getattr(self, "guard_on", False)):
                self.start_watch()


    # -- live camera stream ---------------------------------------------------
    # MJPEG over HTTP from the assistant's own camera, viewable in any
    # browser at http://<pi-ip>:8080/ . Runs in-process, so it coexists with
    # GPT vision snapshots and watch mode.
    # The ov5647 maxes out at analogue gain 8 + 66ms exposure; the garage
    # measured ~0.5 lux, so frames still come out ~30/255 mean. Adaptive
    # digital gain (only when dark, capped 4x) recovers visibility for the
    # live stream and GPT vision at the cost of some noise.
    @staticmethod
    def _brighten(frame, cv2, target=None, max_gain=None):
        if target is None:
            target = VoiceActiveDog.CAMERA_BRIGHTEN_TARGET
        if max_gain is None:
            max_gain = VoiceActiveDog.CAMERA_BRIGHTEN_MAX_GAIN
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
                        # Detection is performed on the IMX500 itself; this
                        # only draws its latest results on the local stream.
                        for detection in assistant._last_ai_detections:
                            x, y, w, h = detection["box"]
                            confirmed_person = (detection["label"] == "person"
                                                and detection.get("person_confirmed", False))
                            possible_person = (detection["label"] == "person"
                                               and not confirmed_person)
                            label_name = ("person" if confirmed_person else
                                          "possible person" if possible_person else
                                          detection["label"])
                            label = f'{label_name} {detection["score"]:.0%}'
                            cv2.rectangle(frame, (x, y), (x + w, y + h),
                                          (40, 220, 40) if not possible_person else
                                          (50, 150, 255), 2)
                            cv2.putText(frame, label, (x, max(16, y - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                        (40, 220, 40) if not possible_person else
                                        (50, 150, 255), 1, cv2.LINE_AA)
                        features = assistant._human_features
                        if time.monotonic() - features.get("timestamp", 0.0) < 1.0:
                            torso = features.get("torso")
                            if torso:
                                x, y, w, h = torso
                                cv2.rectangle(frame, (x, y), (x + w, y + h),
                                              (255, 80, 210), 2)
                                torso_kind = features.get("torso_kind") or "human torso"
                                cv2.putText(frame, f"{torso_kind}: 90% person",
                                            (x, max(16, y - 6)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                                            (255, 80, 210), 1, cv2.LINE_AA)
                            for arm in features.get("arms", []):
                                points = arm["points"]
                                for start, end in zip(points, points[1:]):
                                    cv2.line(frame, start, end, (80, 220, 255), 3)
                                cv2.putText(frame, arm["label"], points[-1],
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                                            (80, 220, 255), 1, cv2.LINE_AA)
                            for x, y, w, h in features.get("hands", []):
                                cv2.rectangle(frame, (x, y), (x + w, y + h),
                                              (80, 255, 120), 2)
                                cv2.putText(frame, "hand", (x, max(16, y - 6)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                            (80, 255, 120), 1, cv2.LINE_AA)
                        # The face overlay is intentionally a second, nested
                        # box rather than a replacement for the AI person
                        # box.  It makes it clear that Doggie sees both the
                        # whole person and the face used for face tracking.
                        if time.monotonic() - assistant._latest_faces_at < 0.8:
                            people = [d["box"] for d in assistant._last_ai_detections
                                      if d["label"] == "person"]
                            for x, y, w, h in assistant._latest_faces:
                                nested = any(assistant._face_is_inside(
                                    (x, y, w, h), person) for person in people)
                                color = (255, 190, 40) if nested else (255, 120, 40)
                                label = "face (person)" if nested else "face"
                                cv2.rectangle(frame, (x, y), (x + w, y + h),
                                              color, 2)
                                cv2.putText(frame, label, (x, max(16, y - 6)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                            color, 1, cv2.LINE_AA)
                        target = assistant._latest_person_target
                        if target:
                            # These regions are derived from the AI person
                            # box. They let the operator see the hierarchy:
                            # full body -> head/upper torso -> recognized face.
                            if target["head"]:
                                x, y, w, h = target["head"]
                                cv2.rectangle(frame, (x, y), (x + w, y + h),
                                              (80, 220, 255), 1)
                                cv2.putText(frame, "head target", (x, max(16, y - 6)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                            (80, 220, 255), 1, cv2.LINE_AA)
                            if target["torso"]:
                                x, y, w, h = target["torso"]
                                cv2.rectangle(frame, (x, y), (x + w, y + h),
                                              (255, 90, 220), 1)
                                cv2.putText(frame, "upper torso", (x, y + 16),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                            (255, 90, 220), 1, cv2.LINE_AA)
                            if target.get("identity") and target["face"]:
                                x, y, _, _ = target["face"]
                                identity = ("owner" if target["identity"] == "owner"
                                            else "unrecognized person")
                                cv2.putText(frame, identity, (x, y + 18),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                            (40, 255, 255), 1, cv2.LINE_AA)
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
        if text == "__web_listen_once__":
            # The authenticated web button bypasses only the wake phrase. It
            # still uses the normal microphone, owner verification, silence
            # endpoint, hard timeout, conversation processing, and TTS path.
            print("web listen: one-shot microphone window opened")
            self.stt.stop_listening()
            wake_thread = getattr(self.stt, "wake_word_thread", None)
            if (wake_thread is not None
                    and wake_thread is not threading.current_thread()):
                wake_thread.join(timeout=2.0)
            if wake_thread is not None and wake_thread.is_alive():
                print("web listen: wake listener did not release microphone")
                return "My microphone is busy. Please press listen again.\nACTIONS:"
            try:
                heard = self.listen()
            except self._sounddevice.PortAudioError as exc:
                print(f"web listen: microphone unavailable: {exc}")
                self._cmd_listening = False
                self.dog.rgb_strip.close()
                return "My microphone is busy. Please press listen again.\nACTIONS:"
            if not heard:
                print("web listen: timed out without a request")
                return "I did not hear a request.\nACTIONS:"
            self.on_heard(heard)
            return self.think(heard, disable_image=False)
        if not self._voice_and_face_authorized(text):
            return "I heard you, but I need my owner's voice before I can follow commands."
        self._last_user_text = text
        if self._is_wifi_scan_query(text):
            return self._build_wifi_scan_reply()
        if self._wifi_scan_choices and time.monotonic() - self._wifi_scan_at < 90:
            selection_reply = self._handle_wifi_selection(text)
            if selection_reply is not None:
                return selection_reply
        direct_action = self._direct_action_for_text(text)
        if direct_action is not None:
            return f"\nACTIONS: {direct_action}"
        self._last_visual_query = self._is_visual_query(text)
        self._last_identity_query = self._is_identity_query(text)
        if self._last_visual_query and not self._camera_available():
            return self._build_camera_unavailable_reply()
        if self._is_git_status_query(text):
            return self._build_git_status_reply()
        if self._is_status_report_query(text):
            return self._build_status_report_reply()
        # attach a fresh battery reading to every round as sensor context
        volts, pct = self.read_battery()
        if volts is not None:
            text = f"{text}\n<<<Battery: {volts}V, about {pct}%>>>"
        text = f"{text}\n<<<DoggieMemory\n{self.memory.build_context()}\n>>>"
        try:
            return super().think(text, disable_image)
        except Exception as exc:
            # The bundled OpenAI client raises connection and DNS errors from
            # inside the streaming loop.  Never let an unavailable network
            # terminate Doggie's main process and trigger a systemd restart.
            print(f"cloud reply unavailable; using offline mode: {exc}")
            return self._build_offline_reply(self._last_user_text)

    def _voice_and_face_authorized(self, text):
        """Gate microphone commands after the owner has enrolled a voice.

        A clear non-owner face is a second required factor. When the camera
        cannot see a usable face, the verified local voice is enough.
        """
        if not self.voice_identity.enrolled():
            return True  # initial enrollment must remain possible
        matched, score, detail = self.voice_identity.verify_pcm(
            self._last_stt_audio, self._last_stt_sample_rate)
        print(f"owner voice check: {detail} ({score:.2f})")
        if not matched:
            return False
        face_status = self.owner_face_status()
        if face_status is False:
            print("owner face check: visible face did not match")
            return False
        return True

    def on_stop(self):
        if self._web_server is not None:
            self._web_server.shutdown()
            self._web_server.server_close()
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
        joined_pairs = {" ".join(words[index:index + 2])
                        for index in range(max(0, len(words) - 1))}
        return ("doggie" in words
                or any(pair in joined_pairs for pair in {"hey doggie", "okay doggie"}))

    @classmethod
    def _is_wake_prefix(cls, text: str) -> bool:
        """True only for a bare greeting that may precede Doggie's name."""
        return cls._normalize_phrase(text).split() == ["hey"]

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

    def _camera_available(self) -> bool:
        """Return whether this response can be based on a live camera frame."""
        return bool(getattr(self, "with_image", False) and getattr(self, "picam2", None))

    @staticmethod
    def _build_camera_unavailable_reply() -> str:
        return (
            "I can't see right now because my camera is unavailable. "
            "I can still hear you and respond to voice commands.\nACTIONS:"
        )

    @classmethod
    def _is_identity_query(cls, text: str) -> bool:
        normalized = cls._normalize_phrase(text)
        return any(pattern in normalized for pattern in cls.IDENTITY_QUERY_PATTERNS)

    @classmethod
    def _is_git_status_query(cls, text: str) -> bool:
        normalized = cls._normalize_phrase(text)
        return any(pattern in normalized for pattern in cls.GIT_STATUS_PATTERNS)

    @classmethod
    def _is_status_report_query(cls, text: str) -> bool:
        normalized = cls._normalize_phrase(text)
        return any(pattern in normalized for pattern in cls.STATUS_REPORT_PATTERNS)

    @classmethod
    def _is_wifi_scan_query(cls, text: str) -> bool:
        normalized = cls._normalize_phrase(text)
        return any(pattern in normalized for pattern in cls.WIFI_SCAN_PATTERNS)

    @classmethod
    def _direct_action_for_text(cls, text: str) -> str | None:
        normalized = cls._normalize_phrase(text)
        padded = f" {normalized} "
        for action, patterns in cls.DIRECT_ACTION_PATTERNS.items():
            if any(
                normalized == pattern or f" {pattern} " in padded
                for pattern in patterns
            ):
                return action
        return None

    def _build_offline_reply(self, text: str) -> str:
        """Provide useful, local-only speech when ChatGPT is unreachable."""
        normalized = self._normalize_phrase(text)
        if any(phrase in normalized for phrase in ("what time", "tell me the time", "time is it")):
            reply = time.strftime("It is %-I:%M %p.")
        elif any(phrase in normalized for phrase in ("what day", "what date", "todays date", "today s date")):
            reply = time.strftime("Today is %A, %B %-d.")
        elif any(phrase in normalized for phrase in ("help", "what can you do", "commands")):
            reply = (
                "I am offline, but I can still sit, stand, lie down, bark, "
                "wag my tail, give a status report, and tell you the time."
            )
        elif any(phrase in normalized for phrase in ("hello", "hi doggie", "hey doggie", "how are you")):
            reply = "I am offline, but I am awake and listening."
        else:
            reply = (
                "I am offline right now. I can still do local commands, "
                "give a status report, and tell you the time."
            )
        return f"{reply}\nACTIONS:"

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

    @staticmethod
    def _safe_spoken_value(value: str) -> str:
        """Keep externally sourced network labels safe and concise for TTS."""
        cleaned = re.sub(r"[^a-zA-Z0-9 _.-]+", "", value).strip()
        return cleaned[:48]

    @staticmethod
    def _has_internet_access() -> bool:
        """Check routed internet access without relying on ICMP/ping."""
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=2):
                return True
        except OSError:
            return False

    def _get_network_status(self) -> dict[str, str | int | bool | None]:
        """Read non-secret Wi-Fi status from NetworkManager.

        This deliberately does not read passwords, saved connection secrets,
        gateway addresses, or scan results from untrusted networks.
        """
        try:
            connection = subprocess.run(
                ["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", "wlan0"],
                capture_output=True,
                text=True,
                timeout=4,
                check=True,
            ).stdout.strip()
            if not connection or connection == "--":
                return {"connected": "no", "internet": False, "ssid": None, "signal": None, "ip": None}

            ssid = connection
            signal = None
            scan = subprocess.run(
                ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list", "ifname", "wlan0", "--rescan", "no"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            for line in scan.stdout.splitlines():
                if not line.startswith("*:"):
                    continue
                parts = line.split(":", 2)
                if len(parts) == 3:
                    ssid = parts[1] or ssid
                    try:
                        signal = int(parts[2])
                    except ValueError:
                        signal = None
                break

            address = subprocess.run(
                ["nmcli", "-g", "IP4.ADDRESS", "device", "show", "wlan0"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            ).stdout.strip().splitlines()
            ip = address[0].split("/", 1)[0] if address else None
            return {
                "connected": "yes",
                "internet": self._has_internet_access(),
                "ssid": self._safe_spoken_value(ssid),
                "signal": signal,
                "ip": self._safe_spoken_value(ip or ""),
            }
        except (OSError, subprocess.SubprocessError):
            return {"connected": "unknown", "internet": None, "ssid": None, "signal": None, "ip": None}

    @staticmethod
    def _saved_wifi_profiles() -> dict[str, str]:
        """Return SSID-to-UUID mappings without reading stored secrets."""
        profiles = {}
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
                capture_output=True, text=True, timeout=5, check=True,
            )
            for line in result.stdout.splitlines():
                uuid, _, connection_type = line.partition(":")
                if connection_type != "802-11-wireless":
                    continue
                ssid_result = subprocess.run(
                    ["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", uuid],
                    capture_output=True, text=True, timeout=3, check=False,
                )
                ssid = ssid_result.stdout.strip()
                if ssid:
                    profiles.setdefault(ssid, uuid)
        except (OSError, subprocess.SubprocessError):
            pass
        return profiles

    def _scan_wifi_choices(self) -> list[dict[str, object]]:
        """Return at most five strongest unique hotspots with safe metadata."""
        saved = self._saved_wifi_profiles()
        try:
            result = subprocess.run(
                ["nmcli", "-t", "--escape", "no", "-f", "SSID,SIGNAL,SECURITY",
                 "device", "wifi", "list", "ifname", "wlan0", "--rescan", "yes"],
                capture_output=True, text=True, timeout=12, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return []

        strongest = {}
        for line in result.stdout.splitlines():
            parts = line.rsplit(":", 2)
            if len(parts) != 3:
                continue
            ssid, signal_text, security = parts
            if not ssid.strip():
                continue
            try:
                signal = int(signal_text)
            except ValueError:
                continue
            previous = strongest.get(ssid)
            if previous is None or signal > previous["signal"]:
                is_open = security.strip() in {"", "--", "NONE"}
                strongest[ssid] = {
                    "ssid": ssid,
                    "spoken": self._safe_spoken_value(ssid) or "unnamed network",
                    "signal": signal,
                    "security": security.strip(),
                    "saved_uuid": saved.get(ssid),
                    "connectable": bool(saved.get(ssid) or is_open),
                    "open": is_open,
                }
        return sorted(strongest.values(), key=lambda item: item["signal"], reverse=True)[:5]

    @staticmethod
    def _active_wifi_profile() -> dict[str, str] | None:
        """Return the active wlan0 connection without exposing credentials."""
        try:
            result = subprocess.run(
                ["nmcli", "-g", "GENERAL.CONNECTION,GENERAL.CON-UUID", "device", "show", "wlan0"],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        values = [line.strip() for line in result.stdout.splitlines()]
        if result.returncode != 0 or len(values) < 2 or not values[1] or values[1] == "--":
            return None
        name = values[0] if values[0] and values[0] != "--" else "current network"
        return {"name": name, "uuid": values[1]}

    def _build_wifi_scan_reply(self) -> str:
        choices = self._scan_wifi_choices()
        self._wifi_scan_choices = choices
        self._wifi_scan_at = time.monotonic()
        if not choices:
            return "I could not find any Wi-Fi hotspots right now. Would you like me to scan again?\nACTIONS:"

        descriptions = []
        for number, choice in enumerate(choices, 1):
            if choice["saved_uuid"]:
                availability = "saved and ready"
            elif choice["open"]:
                availability = "open and ready"
            else:
                availability = "password not saved"
            descriptions.append(
                f"Number {number}, {choice['spoken']}, {choice['signal']} percent, {availability}."
            )
        return (
            "Here are the strongest hotspots. " + " ".join(descriptions)
            + " Which hotspot should I connect to?\nACTIONS:"
        )

    def _handle_wifi_selection(self, text: str) -> str | None:
        """Resolve a numbered/named follow-up and connect only when authorized."""
        normalized = self._normalize_phrase(text)
        if any(phrase in normalized for phrase in ("cancel", "never mind", "nevermind", "stay connected")):
            self._wifi_scan_choices = []
            return "Okay, I will keep my current Wi-Fi connection.\nACTIONS:"

        number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        selected = None
        digit_match = re.search(r"\b([1-5])\b", normalized)
        if digit_match:
            index = int(digit_match.group(1)) - 1
            if index < len(self._wifi_scan_choices):
                selected = self._wifi_scan_choices[index]
        if selected is None:
            for word, number in number_words.items():
                if re.search(rf"\b{word}\b", normalized) and number <= len(self._wifi_scan_choices):
                    selected = self._wifi_scan_choices[number - 1]
                    break
        if selected is None:
            for choice in self._wifi_scan_choices:
                if self._normalize_phrase(str(choice["ssid"])) in normalized:
                    selected = choice
                    break
        if selected is None:
            return "I did not recognize that hotspot. Please say its number or name?\nACTIONS:"
        if not selected["connectable"]:
            return (
                f"I can see {selected['spoken']}, but I do not have its password saved. "
                "Please choose a network marked ready?\nACTIONS:"
            )

        previous = self._active_wifi_profile()
        target_uuid = str(selected["saved_uuid"] or "")
        if previous and (
            (target_uuid and target_uuid == previous["uuid"])
            or self._normalize_phrase(str(selected["ssid"])) == self._normalize_phrase(previous["name"])
        ):
            self._wifi_scan_choices = []
            return f"I am already connected to {selected['spoken']}.\nACTIONS:"

        if selected["saved_uuid"]:
            command = ["nmcli", "connection", "up", "uuid", target_uuid, "ifname", "wlan0"]
        else:
            command = ["nmcli", "device", "wifi", "connect", str(selected["ssid"]), "ifname", "wlan0"]

        previous_spoken = self._safe_spoken_value(previous["name"]) if previous else "my current network"
        try:
            if previous:
                self.tts.say(f"Disconnecting from {previous_spoken}.")
                subprocess.run(
                    ["nmcli", "connection", "down", "uuid", previous["uuid"]],
                    capture_output=True, text=True, timeout=12, check=False,
                )
            self.tts.say(f"Connecting to {selected['spoken']}.")
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            result = None

        if result is not None and result.returncode == 0:
            self._wifi_scan_choices = []
            network = self._get_network_status()
            if network.get("ip"):
                return (
                    f"Connected to {selected['spoken']}. My IP address is "
                    f"{network['ip']}.\nACTIONS:"
                )
            return f"Connected to {selected['spoken']}, but I could not read my IP address yet.\nACTIONS:"

        if previous:
            self.tts.say(f"Connection failed. Reconnecting to {previous_spoken}.")
            try:
                restored = subprocess.run(
                    ["nmcli", "connection", "up", "uuid", previous["uuid"], "ifname", "wlan0"],
                    capture_output=True, text=True, timeout=30, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                restored = None
            if restored is not None and restored.returncode == 0:
                self._wifi_scan_choices = []
                return (
                    f"I could not connect to {selected['spoken']}, so I reconnected to "
                    f"{previous_spoken}.\nACTIONS:"
                )
            return (
                f"I could not connect to {selected['spoken']} or restore {previous_spoken}. "
                "Please check my network locally.\nACTIONS:"
            )
        return f"I could not connect to {selected['spoken']}. Would you like another hotspot?\nACTIONS:"

    def _build_status_report_reply(self) -> str:
        network = self._get_network_status()
        parts = []
        if network["connected"] == "yes":
            network_name = network["ssid"] or "my saved Wi-Fi network"
            parts.append(f"I'm connected to {network_name}.")
            if network.get("internet") is False:
                parts.append("I do not have internet access.")
            if isinstance(network["signal"], int):
                parts.append(f"Wi-Fi signal is {network['signal']} percent.")
            if network["ip"]:
                parts.append(f"My local IP address is {network['ip']}.")
        elif network["connected"] == "no":
            parts.append("I am not connected to Wi-Fi right now.")
        else:
            parts.append("I could not read my Wi-Fi status right now.")

        volts, pct = self.read_battery()
        if volts is not None and pct is not None:
            parts.append(f"Battery is about {pct} percent at {volts} volts.")
        else:
            parts.append("I could not read my battery right now.")
        return f"{' '.join(parts)}\nACTIONS:"

    def _build_startup_announcement(self) -> str:
        """Return a brief, local-only startup announcement for TTS."""
        parts = ["Doggie is ready."]
        network = self._get_network_status()
        if network["connected"] == "yes" and network.get("internet") is True:
            network_name = network["ssid"] or "my saved Wi-Fi network"
            parts.append(f"Doggie is online on {network_name}.")
        elif network["connected"] == "yes":
            network_name = network["ssid"] or "my saved Wi-Fi network"
            parts.append(f"Doggie is connected to {network_name}, but has no internet access.")
        else:
            parts.append("Doggie is offline.")

        if network["connected"] == "yes" and network.get("ip"):
            parts.append(f"Doggie's IP address is {network['ip']}.")

        volts, pct = self.read_battery()
        if volts is not None and pct is not None:
            parts.append(f"Battery is about {pct} percent at {volts} volts.")
        return " ".join(parts)

    def trigger_web_command(self) -> tuple[bool, bool, str]:
        """Deliver one authenticated web command through the normal action path."""
        try:
            command = self._web_commands.get_nowait()
        except queue.Empty:
            return False, False, ""
        return True, True, command

    def _start_web_control_server(self) -> None:
        """Start the authenticated command panel when its password is configured."""
        password = os.environ.get("DOGGIE_CONTROL_PASSWORD", "").strip()
        if not password:
            print("web control disabled: DOGGIE_CONTROL_PASSWORD is not configured")
            return
        # Keep the private safe-shutdown integration compatible with its existing
        # header while the browser controller uses the normal password login.
        shutdown_secret = os.environ.get("DOGGIE_CONTROL_TOKEN", "").strip() or password

        module = self

        class Handler(BaseHTTPRequestHandler):
            def _session_valid(self) -> bool:
                cookie = self.headers.get("Cookie", "")
                session = ""
                for part in cookie.split(";"):
                    name, separator, value = part.strip().partition("=")
                    if separator and name == "doggie_session":
                        session = value
                        break
                expires = module._web_sessions.get(session, 0)
                return bool(session) and expires > time.time()

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "default-src 'self'; img-src http:; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, payload: dict) -> None:
                self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

            def _forbidden(self) -> None:
                self._json(403, {"error": "Sign in required"})

            def _shutdown_authorized(self) -> bool:
                supplied = (
                    self.headers.get("X-Doggie-Control-Password", "")
                    or self.headers.get("X-Doggie-Control-Token", "")
                )
                return bool(supplied) and hmac.compare_digest(supplied, shutdown_secret)

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/health":
                    self._json(200, {"status": "ok"})
                    return
                if path == "/internal/safe-shutdown-status":
                    if not self._shutdown_authorized():
                        self._forbidden()
                        return
                    self._json(200, dict(module._shutdown_status))
                    return
                if path == "/api/status":
                    if not self._session_valid():
                        self._forbidden()
                        return
                    self._json(200, {"commands": sorted(module.WEB_COMMANDS)})
                    return
                if path != "/":
                    self._json(404, {"error": "Not found"})
                    return
                if not self._session_valid():
                    page = b'''<!doctype html><title>Doggie Control</title><style>body{font:16px system-ui;max-width:420px;margin:4rem auto;background:#101827;color:#eef;padding:1rem}input,button{font:inherit;padding:.7rem;margin:.4rem 0;width:100%;box-sizing:border-box}button{background:#38bdf8;border:0;border-radius:.4rem}</style><h1>Doggie Control</h1><p>Private control panel. Sign in with your password.</p><form method="post" action="/login"><input type="password" name="password" autocomplete="current-password" placeholder="Password" required><button>Sign in</button></form>'''
                    self._send(200, page, "text/html; charset=utf-8")
                    return
                page = b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Doggie Safe Controller</title><style>*{box-sizing:border-box}body{margin:0;background:#07101b;color:#eef;font:16px system-ui;overflow:hidden}.camera{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;opacity:.45}.ui{position:relative;min-height:100vh;padding:1rem;display:flex;align-items:end;justify-content:space-between;background:linear-gradient(transparent 35%,#06101ddd)}h1{position:absolute;top:.5rem;left:1rem;font-size:1rem}.pad{display:grid;grid-template:repeat(3,58px)/repeat(3,58px);gap:5px}.pad button{font-size:20px}.up{grid-column:2}.left{grid-column:1;grid-row:2}.mid{grid-column:2;grid-row:2}.right{grid-column:3;grid-row:2}.down{grid-column:2;grid-row:3}button{border:1px solid #7dd3fc;border-radius:16px;background:#0e2947e8;color:#fff;touch-action:manipulation}button:active{background:#0284c7}button:disabled{opacity:.35}.rightside{display:flex;align-items:end;gap:1rem}.actions{display:grid;grid-template-columns:repeat(2,76px);gap:6px}.actions button{height:58px;font-size:12px;font-weight:700}.actions .listen{grid-column:1/-1;background:#075985}.label{text-align:center;font-size:11px;margin:0 0 5px}.note{position:absolute;top:2.5rem;left:1rem;right:1rem;font-size:12px;max-width:42rem}@media(max-width:620px){.ui{padding:.7rem}.pad{grid-template:repeat(3,50px)/repeat(3,50px)}.actions{grid-template-columns:repeat(2,68px)}.actions button{height:50px}.rightside{gap:.5rem}}</style><img class="camera" id="camera" alt="Doggie live camera"><main class="ui"><h1>Doggie Safe Controller</h1><p class="note">Uses Doggie's normal command path. Walking and unrestricted head movement stay locked for safety.</p><section><p class="label">BODY</p><div class="pad"><button class="up" data-command="stand">&#9650;</button><button class="left" disabled>&#9664;</button><button class="mid" data-command="stop">&#9632;</button><button class="right" disabled>&#9654;</button><button class="down" data-command="lie down">&#9660;</button></div></section><section class="rightside"><div><p class="label">HEAD (SAFE)</p><div class="pad"><button class="up" data-command="nod">&#9650;</button><button class="left" disabled>&#9664;</button><button class="mid" data-command="shake head">&#9679;</button><button class="right" disabled>&#9654;</button><button class="down" data-command="head down">&#9660;</button></div></div><div><p class="label">ACTIONS</p><div class="actions"><button data-command="sit">SIT</button><button data-command="stand">STAND</button><button data-command="bark">BARK</button><button data-command="lie down">LAY DOWN</button><button class="listen" data-command="listen">LISTEN</button></div></div></section></main><p id="result" style="position:fixed;bottom:.5rem;left:50%;transform:translateX(-50%);margin:0"></p><script>document.getElementById('camera').src='http://'+window.location.hostname+':8080/stream';async function send(c){const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:c})});const d=await r.json();document.getElementById('result').textContent=d.status||d.error||'Request failed'}document.querySelectorAll('[data-command]').forEach(b=>b.onclick=()=>send(b.dataset.command))</script>'''
                responsive_css = b'''<style>
body{overflow:auto;min-height:100svh}
.ui{min-height:100svh;height:auto;padding-bottom:max(1rem,env(safe-area-inset-bottom));gap:1rem}
button{min-width:48px;min-height:48px}
@media(max-width:760px){
  .ui{display:flex;flex-direction:column;align-items:stretch;justify-content:flex-end;
      gap:.65rem;padding:5.2rem .75rem max(3.25rem,calc(env(safe-area-inset-bottom) + 2.5rem))}
  .ui>section:first-of-type{align-self:center}
  .rightside{display:grid;grid-template-columns:minmax(150px,1fr) minmax(142px,1fr);
             align-items:end;justify-items:center;gap:.75rem;width:100%}
  .pad{grid-template:repeat(3,48px)/repeat(3,48px);gap:5px}
  .actions{grid-template-columns:repeat(2,minmax(64px,1fr));width:100%;max-width:180px}
  .actions button{height:48px;min-width:0}
  .label{margin-bottom:4px}
  .note{top:2.2rem;font-size:11px;line-height:1.25}
}
@media(max-width:350px){
  .rightside{grid-template-columns:1fr;gap:.5rem}
  .ui{padding-top:5.6rem}
}
@media(max-height:560px) and (orientation:landscape){
  .ui{display:grid;grid-template-columns:repeat(3,max-content);align-items:end;
      justify-content:space-around;padding-top:4.2rem;overflow:auto}
  .ui>section:first-of-type{align-self:end}
  .rightside{display:contents}
  .pad{grid-template:repeat(3,44px)/repeat(3,44px)}
  .actions button{height:44px;min-height:44px}
}
</style>'''
                page = page.replace(b"</head>", responsive_css + b"</head>", 1)
                if responsive_css not in page:
                    page = page.replace(b"</style>", b"</style>" + responsive_css, 1)
                self._send(200, page, "text/html; charset=utf-8")

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 4096)
                except ValueError:
                    self._json(400, {"error": "Invalid request"})
                    return
                raw = self.rfile.read(length)
                if path == "/internal/safe-shutdown":
                    if not self._shutdown_authorized():
                        self._forbidden()
                        return
                    if module._shutdown_status.get("state") in {
                        "queued", "lowering_rear", "lowering_front"
                    }:
                        self._json(409, dict(module._shutdown_status))
                        return
                    try:
                        module._web_commands.put_nowait("safe shutdown")
                    except queue.Full:
                        self._json(429, {"error": "Command queue is full"})
                        return
                    module._shutdown_status = {"state": "queued", "detail": "waiting for live controller"}
                    self._json(202, dict(module._shutdown_status))
                    return
                if path == "/login":
                    form = parse_qs(raw.decode("utf-8", errors="replace"))
                    supplied = (form.get("password") or [""])[0]
                    if not hmac.compare_digest(supplied, password):
                        self._forbidden()
                        return
                    session = secrets.token_urlsafe(32)
                    module._web_sessions = {session: time.time() + 3600}
                    self.send_response(303)
                    self.send_header("Set-Cookie", f"doggie_session={session}; HttpOnly; SameSite=Strict; Path=/")
                    self.send_header("Location", "/")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                if path != "/api/command" or not self._session_valid():
                    self._forbidden()
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(400, {"error": "Invalid request"})
                    return
                command = str(payload.get("command", "")).strip().lower()
                command_text = module.WEB_COMMANDS.get(command)
                if command_text is None:
                    self._json(400, {"error": "Command is not allowed"})
                    return
                try:
                    module._web_commands.put_nowait(command_text)
                except queue.Full:
                    self._json(429, {"error": "Command queue is full"})
                    return
                self._json(202, {"status": f"Queued: {command}"})

            def log_message(self, format, *args):
                return

        host = os.environ.get("DOGGIE_CONTROL_HOST", "127.0.0.1").strip()
        if host not in {"127.0.0.1", "0.0.0.0"}:
            print("web control disabled: DOGGIE_CONTROL_HOST must be 127.0.0.1 or 0.0.0.0")
            return
        try:
            self._web_server = ThreadingHTTPServer((host, 8093), Handler)
        except OSError as exc:
            print(f"web control disabled: {exc}")
            return
        self._web_server.daemon_threads = True
        self._web_server_thread = threading.Thread(
            target=self._web_server.serve_forever,
            name="doggie-web-control",
            daemon=True,
        )
        self._web_server_thread.start()
        print(f"web control available at http://{host}:8093/")

    @staticmethod
    def _web_camera_host() -> str:
        """Configured LAN address used only for the controller camera background."""
        return os.environ.get("DOGGIE_CONTROL_CAMERA_HOST", "127.0.0.1").strip()

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
