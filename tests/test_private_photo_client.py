"""Private photo publication is explicit and requires an advertised schema."""

import unittest
from unittest.mock import patch
from modules import cloud, remote

SCHEMA = {
    "paths": {
        "/v1/photos/publish": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/PhotoPublishIn"}
                        }
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "PhotoPublishIn": {
                "properties": {
                    "visibility": {
                        "type": "string",
                        "enum": ["public", "private"],
                        "default": "public",
                    }
                }
            }
        }
    },
}


class PrivatePhotoClientTests(unittest.TestCase):
    def test_private_is_forwarded_only_after_schema_confirmation(self):
        with (
            patch.object(remote, "request", return_value=SCHEMA) as metadata,
            patch.object(cloud, "_call", return_value={"ok": True}) as post,
        ):
            cloud.publish_photo_items(
                "synthetic",
                "http://fixture.invalid",
                [{"ticket": "fixture", "frame": "fixture"}],
                visibility="private",
            )
        metadata.assert_called_once_with("GET", "/openapi.json", retry_busy=False)
        self.assertEqual(post.call_args.args[2]["visibility"], "private")

    def test_old_schema_prevents_upload_and_publication_without_fallback(self):
        with (
            patch.object(remote, "request", return_value={}),
            patch.object(cloud, "upload_photos") as upload,
            patch.object(cloud, "_call") as post,
        ):
            with self.assertRaises(remote.RemoteError):
                cloud.publish_photos(
                    "synthetic",
                    "http://fixture.invalid",
                    [b"fixture"],
                    visibility="private",
                )
        upload.assert_not_called()
        post.assert_not_called()

    def test_legacy_public_payload_stays_unchanged(self):
        with (
            patch.object(remote, "request") as metadata,
            patch.object(cloud, "_call", return_value={"ok": True}) as post,
        ):
            cloud.publish_photo_items(
                "synthetic",
                "http://fixture.invalid",
                [{"ticket": "fixture", "frame": "fixture"}],
            )
        metadata.assert_not_called()
        self.assertNotIn("visibility", post.call_args.args[2])

    def test_invalid_choice_is_rejected_before_upload(self):
        with patch.object(cloud, "upload_photos") as upload:
            with self.assertRaises(ValueError):
                cloud.publish_photos(
                    "synthetic", "http://fixture.invalid", [], visibility="friends"
                )
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
