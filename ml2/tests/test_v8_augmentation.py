"""Augmented real H.264 fixtures retain VFR PTS and contain no audio."""
from pathlib import Path
import tempfile
import unittest
import av
import numpy as np
from eval.v8_end_to_end import augment_video
from video_fixtures import normalized_mp4


class AugmentationTests(unittest.TestCase):
    def test_input_rotation_metadata_is_applied_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4';target=root/'oriented.mp4'
            normalized_mp4(source,rotation=90)
            augment_video(source,target,'original')
            with av.open(str(target)) as video:
                frame=next(video.decode(video=0))
                self.assertEqual((frame.width,frame.height),(32,64))
                self.assertEqual(frame.rotation,0)

    def test_mirror_and_rotation_preserve_every_source_pts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4'
            normalized_mp4(source,(2000,2100,2200,2900,3000,3600))
            with av.open(str(source)) as video:
                original=[float(f.pts*f.time_base) for f in video.decode(video=0)]
            for variant in ['original','mirror','rotate_20','rotate_-20']:
                target=root/f'{variant}.mp4';augment_video(source,target,variant)
                with av.open(str(target)) as video:
                    self.assertEqual(len(video.streams.audio),0)
                    times=[float(f.pts*f.time_base) for f in video.decode(video=0)]
                np.testing.assert_allclose(times,original,atol=1e-6)


if __name__=='__main__':unittest.main()
