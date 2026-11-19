"""Cloud-storage smoke tests with a fake S3 client (no network or credentials needed).
Run: python -m unittest tests.test_cloud_video
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import cloud, config


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.fail = False

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        if self.fail:
            raise OSError("simulated network error")
        self.objects[key] = Path(path).read_bytes()

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[Key])}

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key])

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


class CloudVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = FakeS3()
        self.patches = [
            patch.object(config, "DATA_DIR", self.root),
            patch.object(cloud, "enabled", return_value=True),
            patch.object(cloud, "_client", return_value=self.fake),
            patch.object(cloud, "_bucket", return_value="videos"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_original_video_persists_and_restores(self):
        path = self.root / "users" / "u123456" / "jobs" / "j1" / "source.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"video bytes")
        self.assertTrue(cloud.store(path))
        self.assertTrue(path.exists())
        path.unlink()
        self.assertTrue(cloud.fetch(path))
        self.assertEqual(path.read_bytes(), b"video bytes")
        self.assertTrue(cloud.store(path, delete_local=True))
        self.assertFalse(path.exists())

    def test_live_segment_offload_delete_and_restore(self):
        path = self.root / "users" / "u123456" / "live" / "buffer" / "p01_00001.ts"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"mpegts")
        self.assertTrue(cloud.store(path, delete_local=True))
        self.assertFalse(path.exists())
        self.assertTrue(cloud.fetch(path))
        self.assertEqual(path.read_bytes(), b"mpegts")
        cloud.remove(path)
        self.assertFalse(cloud.exists_remote(path))

    def test_upload_failure_retains_local_file(self):
        path = self.root / "video.mp4"
        path.write_bytes(b"important")
        self.fake.fail = True
        self.assertFalse(cloud.store(path, delete_local=True))
        self.assertEqual(path.read_bytes(), b"important")


if __name__ == "__main__":
    unittest.main()
