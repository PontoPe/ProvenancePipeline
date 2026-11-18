"""Synthetic adapter fixtures; these do not prove registry compatibility."""
import base64
import importlib.util
import json
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[2] / "scripts" / "bundle_publication.py"


class BundlePublicationTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("bundle_publication", MODULE)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_verified_ndjson_decoder(self):
        statement = {"_type": "https://in-toto.io/Statement/v1"}
        envelope = {"payloadType": "application/vnd.in-toto+json", "payload":
                    base64.b64encode(json.dumps(statement).encode()).decode()}
        self.assertEqual(self.module.decode_verified(json.dumps(envelope)), [statement])
        for bad in ("", "[]", "null", "{}", '{"payload":"!!!"}',
                    '{"payloadType":"foreign","payloadType":"application/vnd.in-toto+json","payload":"e30="}',
                    json.dumps({**envelope, "payload": base64.b64encode(b'{"subject":[],"subject":[{}]}').decode()}),
                    json.dumps({**envelope, "payloadType": "foreign"}),
                    json.dumps(envelope) + "\n{}"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.module.decode_verified(bad)

    def test_descriptor_must_be_discoverable_and_bound(self):
        media = "application/vnd.dev.sigstore.bundle.v0.3+json"
        digest = "sha256:" + "a" * 64
        bundle_digest = "sha256:" + "b" * 64
        manifest_digest = "sha256:" + "c" * 64
        index = {"schemaVersion": 2, "manifests": [{"digest": manifest_digest,
                 "artifactType": media, "mediaType": "application/vnd.oci.image.manifest.v1+json", "size": 100}]}
        manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {"digest": "sha256:" + "d" * 64, "size": 2,
                               "mediaType": "application/vnd.oci.empty.v1+json"},
                    "artifactType": media, "subject": {"digest": digest},
                    "layers": [{"digest": bundle_digest, "mediaType": media, "size": 200}]}
        self.module.check_descriptor(index, manifest, manifest_digest, digest, bundle_digest, 100, 200)
        mutations = [(index, {**manifest, "schemaVersion": 1}),
                     (index, {**manifest, "config": {}}),
                     ({**index, "manifests": [{**index["manifests"][0], "size": -1}]}, manifest),
                     ({**index, "manifests": [{**index["manifests"][0], "mediaType": "text/plain"}]}, manifest),
                     (index, {**manifest, "layers": [{**manifest["layers"][0], "size": -1}]}),
                     ({"manifests": []}, manifest),
                     ({"manifests": [{"digest": manifest_digest, "artifactType":
                                      "application/vnd.oci.empty.v1+json"}]}, manifest),
                     (index, {**manifest, "subject": {"digest": "sha256:" + "d" * 64}}),
                     (index, {**manifest, "layers": []}),
                     (index, {**manifest, "layers": [{"digest": digest, "mediaType": media}]})]
        for candidate, attached in mutations:
            with self.subTest(candidate=candidate, attached=attached), self.assertRaises(ValueError):
                self.module.check_descriptor(candidate, attached, manifest_digest, digest, bundle_digest, 100, 200)


if __name__ == "__main__":
    unittest.main()
