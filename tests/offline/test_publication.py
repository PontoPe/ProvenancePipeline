"""Synthetic decoded statements; these are NOT verified signatures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_contracts import ROOT, checker

DIGEST = "a" * 64
REVISION = "b" * 40
IMAGE = "ghcr.io/pontope/provenancepipeline"
IDENTITY = "https://github.com/PontoPe/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main"
REPOSITORY = "https://github.com/PontoPe/ProvenancePipeline"


def statement():
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": IMAGE, "digest": {"sha256": DIGEST}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": REPOSITORY + "/build-types/github-actions/v1",
                "externalParameters": {"workflow": {
                    "repository": REPOSITORY, "ref": "refs/heads/main",
                    "path": ".github/workflows/release.yml"}},
                "resolvedDependencies": [{
                    "uri": "git+" + REPOSITORY + "@refs/heads/main",
                    "digest": {"gitCommit": REVISION}}]},
            "runDetails": {"builder": {"id": IDENTITY}}}}


def check(value, ref=IMAGE + "@sha256:" + DIGEST, revision=REVISION):
    with tempfile.TemporaryDirectory(dir=ROOT / "tests/offline") as directory:
        path = Path(directory) / "statements.json"
        path.write_text(json.dumps(value))
        return checker().check_publication(path, ref, revision)


class PublicationTests(unittest.TestCase):
    def test_exact_own_statement_passes_without_claiming_crypto_or_admission(self):
        result = check([statement()])
        self.assertEqual(result["status"], "publication-content-valid")
        self.assertIs(result["cryptographic_verification_performed"], False)
        self.assertIs(result["consumer_compatibility_proven"], False)

    def test_missing_or_divergent_content_is_rejected(self):
        mutations = [
            lambda s: s.update(_type="https://in-toto.io/Statement/v0.1"),
            lambda s: s.update(subject=[]),
            lambda s: s["subject"][0]["digest"].update(sha256="c" * 64),
            lambda s: s["subject"][0].update(name=IMAGE + "-other"),
            lambda s: s.update(predicateType="https://spdx.dev/Document"),
            lambda s: s["predicate"]["runDetails"]["builder"].update(id=IDENTITY + "-other"),
            lambda s: s["predicate"]["buildDefinition"].update(buildType="https://actions.github.io/buildtypes/workflow/v1"),
            lambda s: s["predicate"]["buildDefinition"]["externalParameters"]["workflow"].update(ref="refs/tags/v1"),
            lambda s: s["predicate"]["buildDefinition"]["externalParameters"]["workflow"].update(repository="https://github.com/other/repo"),
            lambda s: s["predicate"]["buildDefinition"]["externalParameters"]["workflow"].update(path=".github/workflows/other.yml"),
            lambda s: s["predicate"]["buildDefinition"].update(resolvedDependencies=[]),
            lambda s: s["predicate"]["buildDefinition"]["resolvedDependencies"][0]["digest"].update(gitCommit="c" * 40),
            lambda s: s.pop("predicate"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                value = copy.deepcopy(statement())
                mutate(value)
                with self.assertRaises(ValueError):
                    check([value])
        for value in ([], {}, None, [None], [statement(), {}]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                check(value)
        for ref in (IMAGE + ":latest", IMAGE + "@sha256:" + "A" * 64,
                    IMAGE + "@sha256:" + DIGEST + "\n"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                check([statement()], ref=ref)
        with self.assertRaises(ValueError):
            check([statement()], revision="not-a-commit")


if __name__ == "__main__":
    unittest.main()
