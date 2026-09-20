from unicorn_cloak.__main__ import reset_speaking_state_and_close_mouth
from unicorn_cloak.audio import SpeakingState
from unicorn_cloak.config import MotionConfig
from unicorn_cloak.render import RenderWindow

from qt_helpers import make_test_rig


def test_reset_speaking_state_and_close_mouth_forces_the_mouth_shut(qapp):
    # Regression 2026-09-20, owner's report: "the audio file stops but
    # the mouth keeps moving." update_speaking's attack/hold/release
    # envelope only advances when it's actually called, and nothing ever
    # calls it again once file playback fully stops -- leaving talk_level
    # stuck at whatever nonzero level it last reached (see this
    # function's own docstring in __main__.py for the full mechanism).
    rig = make_test_rig()  # sprite 2 has talk_state=1 (mild)
    window = RenderWindow(rig, MotionConfig())
    window.set_talk_level(2)
    window.set_envelope(0.9)

    result = reset_speaking_state_and_close_mouth(window)

    assert window.talk_level == 0
    assert window.current_envelope == 0.0
    assert result == SpeakingState()


def test_reset_speaking_state_and_close_mouth_is_harmless_while_muted(qapp):
    # OBS mute (set_muted) already forces effective_talk_level to 0 via
    # its own, separate path -- this just confirms the two don't fight:
    # resetting talk_level while muted still leaves the mouth closed,
    # not accidentally reopened.
    rig = make_test_rig()
    window = RenderWindow(rig, MotionConfig())
    window.set_muted(True)

    reset_speaking_state_and_close_mouth(window)

    assert window.effective_talk_level == 0
