"""Host tests for deterministic RP2040 release provenance."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[1]
SDK_COMMIT = "a1438dff1d38bd9c65dbd693f0e5db4b9ae91779"
COMPILER_ID = "GNU-13.3.1"
SPEC = importlib.util.spec_from_file_location(
    "release_provenance", SOURCE_DIR / "release_provenance.py"
)
assert SPEC and SPEC.loader
release_provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_provenance)


class ReleaseProvenanceTests(unittest.TestCase):
    def identity(self, variant: str, **overrides: str):
        return release_provenance.compute_identity(
            SOURCE_DIR,
            variant,
            sdk_commit=overrides.get("sdk_commit", SDK_COMMIT),
            compiler_id=overrides.get("compiler_id", COMPILER_ID),
        )

    def test_unrelated_worktree_file_does_not_change_identity(self) -> None:
        before = self.identity("release")
        with tempfile.NamedTemporaryFile(
            dir=SOURCE_DIR, prefix="unrelated-dirty-", suffix=".tmp"
        ) as probe:
            probe.write(b"this file is intentionally outside the controlled input set")
            probe.flush()
            after = self.identity("release")
        self.assertEqual(before["source_sha256"], after["source_sha256"])
        self.assertEqual(before["emitted_build"], after["emitted_build"])

    def test_variants_have_distinct_exact_wire_identities(self) -> None:
        release = self.identity("release")
        fi1 = self.identity("fi1")
        self.assertRegex(release["emitted_build"], r"^rel-[0-9a-f]{24}$")
        self.assertRegex(fi1["emitted_build"], r"^fi1-[0-9a-f]{24}$")
        self.assertNotEqual(release["source_sha256"], fi1["source_sha256"])
        self.assertEqual(len(release["emitted_cfg"]), 16)
        self.assertEqual(release["emitted_cfg"], fi1["emitted_cfg"])

    def test_generated_header_uses_computed_values(self) -> None:
        expected = self.identity("release")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "build_id.h"
            args = type(
                "Args",
                (),
                {
                    "source_dir": SOURCE_DIR,
                    "variant": "release",
                    "debug_usb": False,
                    "pico_board": "pico",
                    "build_type": "Release",
                    "sdk_commit": SDK_COMMIT,
                    "compiler_id": COMPILER_ID,
                    "output": output,
                },
            )()
            release_provenance.write_header(args)
            actual = release_provenance._read_header(output)
        self.assertEqual(actual["WSL_BUILD_ID"], expected["emitted_build"])
        self.assertEqual(actual["WSL_CFG_SHA"], expected["emitted_cfg"])
        self.assertEqual(actual["WSL_SOURCE_SHA256"], expected["source_sha256"])
        self.assertEqual(actual["WSL_BUILD_VARIANT"], "release")
        self.assertEqual(actual["WSL_PICO_SDK_COMMIT"], SDK_COMMIT)
        self.assertEqual(actual["WSL_C_COMPILER_ID"], COMPILER_ID)

    def test_identity_json_is_canonicalizable(self) -> None:
        identity = self.identity("release")
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        self.assertEqual(identity, json.loads(encoded))

    def test_sdk_or_compiler_change_alters_runtime_build_id(self) -> None:
        baseline = self.identity("release")
        other_sdk = self.identity(
            "release", sdk_commit="b1438dff1d38bd9c65dbd693f0e5db4b9ae91779"
        )
        other_compiler = self.identity("release", compiler_id="GNU-14.2.0")
        self.assertNotEqual(baseline["emitted_build"], other_sdk["emitted_build"])
        self.assertNotEqual(baseline["emitted_build"], other_compiler["emitted_build"])


if __name__ == "__main__":
    unittest.main()
