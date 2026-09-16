"""Only independently aligned feature frames may supply showcase audio."""

from pathlib import Path

import pytest

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')

from tools.add_showcase_audio import align  # noqa: E402


def write_video(path: Path, frames):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (160, 120))
    assert writer.isOpened()
    for frame in frames:
        writer.write(frame)
    writer.release()


def test_independent_frames_find_original_feature_start(tmp_path):
    rng = np.random.default_rng(17)
    frames = [rng.integers(0, 256, (120, 160, 3), dtype=np.uint8) for _ in range(80)]
    source, capture = tmp_path / 'feature.avi', tmp_path / 'capture.avi'
    write_video(source, frames)
    write_video(capture, frames[20:60])
    proof = align(capture, source, (0, 0, 160, 120))
    assert proof['source_start_seconds'] == pytest.approx(2.0)
    assert proof['duration_seconds'] == pytest.approx(4.0)


def test_static_screen_cannot_establish_soundtrack_timing(tmp_path):
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 256, (120, 160, 3), dtype=np.uint8)
    source, capture = tmp_path / 'feature.avi', tmp_path / 'capture.avi'
    write_video(source, [frame] * 80)
    write_video(capture, [frame] * 40)
    with pytest.raises(ValueError):
        align(capture, source, (0, 0, 160, 120))
