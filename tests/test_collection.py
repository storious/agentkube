from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / ".agents" / "package.json"
CATALOG = ROOT / "catalog" / "catalog.json"
SPECIALIST_IDS = {
    "repository-scout",
    "docs-editor",
    "short-patcher",
    "focused-tester",
}


class CollectionTests(unittest.TestCase):
    def test_root_package_is_strict_v2_and_lists_local_resources(self) -> None:
        package = json.loads(PACKAGE.read_text(encoding="utf-8"))

        self.assertEqual(
            set(package),
            {"format", "id", "version", "description", "instructions", "resources"},
        )
        self.assertEqual(package["format"], "agulater/package/v2")
        self.assertEqual(package["id"], "agentkube")
        self.assertEqual(package["version"], "0.2.3-rc.1")
        self.assertTrue((PACKAGE.parent / package["instructions"]).is_file())
        resources = package["resources"]
        self.assertEqual(
            {skill["id"] for skill in resources["skills"]},
            {"grill-me", "grilling"},
        )
        self.assertEqual(
            {plugin["id"] for plugin in resources["plugins"]},
            {"coordinator", "web-search"},
        )
        for collection in ("skills", "plugins"):
            for resource in resources[collection]:
                with self.subTest(collection=collection, resource=resource["id"]):
                    self.assertTrue(
                        (PACKAGE.parent / resource["path"]).resolve().is_dir()
                    )
        package_roots = {
            (PACKAGE.parent / resource["path"]).resolve()
            for resource in resources["packages"]
        }
        self.assertEqual({path.parent.name for path in package_roots}, SPECIALIST_IDS)
        self.assertTrue(
            all((path / "package.json").is_file() for path in package_roots)
        )

        pools = json.loads(
            (ROOT / ".agents" / "pools.json").read_text(encoding="utf-8")
        )
        self.assertEqual(pools["format"], "agulater/pools/v2")
        self.assertEqual(pools["default_pool"], "deepseek")
        pools_by_id = {pool["id"]: pool for pool in pools["pools"]}
        self.assertEqual(
            set(pools_by_id),
            {"deepseek", "glm-coding", "codex-account", "local-example"},
        )
        self.assertEqual(pools_by_id["deepseek"]["engine"], "native")
        self.assertEqual(
            pools_by_id["glm-coding"]["endpoint"],
            "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
        )
        self.assertEqual(
            pools_by_id["local-example"]["endpoint"],
            "http://127.0.0.1:51100/v1/chat/completions",
        )
        self.assertEqual(pools_by_id["local-example"]["reasoning_effort"], "medium")
        self.assertEqual(pools_by_id["codex-account"]["engine"], "codex")
        self.assertEqual(pools_by_id["codex-account"]["max_concurrency"], 1)
        self.assertNotIn("endpoint", pools_by_id["codex-account"])
        self.assertNotIn("reasoning_effort", pools_by_id["codex-account"])

    def test_skill_names_match_their_directories(self) -> None:
        package = json.loads(PACKAGE.read_text(encoding="utf-8"))
        for resource in package["resources"]["skills"]:
            skill = (PACKAGE.parent / resource["path"]).resolve()
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            match = re.search(r"^name:\s*(\S+)\s*$", text, re.MULTILINE)
            with self.subTest(skill=resource["id"]):
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), resource["id"])
                self.assertTrue((skill / "agents" / "openai.yaml").is_file())
                notice = (skill / "THIRD_PARTY_NOTICE.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("MIT License", notice)
                self.assertIn("Copyright (c) 2026 Matt Pocock", notice)

    def test_grilling_skills_keep_fact_finding_targeted(self) -> None:
        for skill_id in ("grill-me", "grilling"):
            text = (
                PACKAGE.parent / "skills" / skill_id / "SKILL.md"
            ).read_text(encoding="utf-8")
            with self.subTest(skill=skill_id):
                self.assertIn(
                    "do not inventory the environment before Round 1",
                    text,
                )
                self.assertIn(
                    "Ambiguity about what the user means or which scope they intend "
                    "is a decision question, not a fact gap",
                    text,
                )
                self.assertIn(
                    "when no path, symbol, command, or source is named, ask for "
                    "one in Round 1",
                    text,
                )
                self.assertIn("Use the narrowest named source", text)

    def test_specialist_packages_have_frozen_profiles_and_harnesses(self) -> None:
        expected = {
            "repository-scout": ("read", 16384, "medium", 6, 8, 1536, 600),
            "docs-editor": ("write", 16384, "medium", 6, 12, 2048, 900),
            "short-patcher": ("write", 32768, "high", 8, 16, 3072, 1200),
            "focused-tester": ("write", 16384, "medium", 8, 12, 2048, 1200),
        }
        for specialist_id, values in expected.items():
            package_root = ROOT / "agents" / specialist_id / ".agents"
            package = json.loads(
                (package_root / "package.json").read_text(encoding="utf-8")
            )
            harness = json.loads(
                (package_root / package["profile"]["harness"]).read_text(
                    encoding="utf-8"
                )
            )
            effect, window, effort, rounds, tools, tokens, timeout = values
            with self.subTest(specialist=specialist_id):
                self.assertEqual(package["format"], "agulater/package/v2")
                self.assertEqual(package["id"], specialist_id)
                self.assertEqual(package["profile"]["workspace_effect"], effect)
                self.assertTrue((package_root / package["instructions"]).is_file())
                contexts = package["resources"]["contexts"]
                self.assertEqual(package["profile"]["contexts"], [contexts[0]["id"]])
                self.assertTrue((package_root / contexts[0]["path"]).is_file())
                self.assertEqual(harness["format"], "agulater/harness/v1")
                self.assertEqual(harness["requirements"]["min_context_window"], window)
                self.assertEqual(harness["defaults"]["reasoning_effort"], effort)
                self.assertEqual(harness["defaults"]["max_rounds"], rounds)
                self.assertEqual(harness["defaults"]["max_tool_calls"], tools)
                self.assertEqual(harness["defaults"]["max_tokens"], tokens)
                self.assertEqual(harness["defaults"]["timeout_seconds"], timeout)
                self.assertEqual(harness["result"]["format"], "agul/handoff/v1")
                self.assertEqual(harness["result"]["summary_max_chars"], 240)
                self.assertEqual(harness["result"]["evidence_max_items"], 4)

    def test_catalog_has_unique_versioned_git_entries(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

        self.assertEqual(catalog["format"], "agulater/catalog/v1")
        entries = catalog["entries"]
        self.assertEqual(len({entry["id"] for entry in entries}), len(entries))
        self.assertTrue(SPECIALIST_IDS <= {entry["id"] for entry in entries})
        self.assertNotIn("self-maintainer", {entry["id"] for entry in entries})
        self.assertNotIn("agentkube", {entry["id"] for entry in entries})
        catalog_by_id = {entry["id"]: entry for entry in entries}
        expected_versions = {
            "coordinator": ["0.3.2-rc.1"],
            "repository-scout": ["0.1.1"],
            "docs-editor": ["0.1.1"],
            "short-patcher": ["0.1.1"],
            "focused-tester": ["0.1.1"],
            "grill-me": ["0.1.1"],
            "grilling": ["0.1.1"],
            "web-search": ["0.3.0"],
        }
        self.assertEqual(
            {
                entry_id: [version["version"] for version in entry["versions"]]
                for entry_id, entry in catalog_by_id.items()
            },
            expected_versions,
        )
        for specialist_id in SPECIALIST_IDS:
            package = json.loads(
                (
                    ROOT
                    / "agents"
                    / specialist_id
                    / ".agents"
                    / "package.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                catalog_by_id[specialist_id]["versions"][-1]["version"],
                package["version"],
            )
        for plugin_id in ("coordinator", "web-search"):
            manifest = json.loads(
                (ROOT / "plugins" / plugin_id / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                catalog_by_id[plugin_id]["versions"][-1]["version"],
                manifest["version"],
            )
        for entry in entries:
            with self.subTest(entry=entry["id"]):
                self.assertIn(entry["kind"], {"package", "skill", "plugin"})
                self.assertTrue(entry["description"])
                self.assertTrue(entry["versions"])
                for version in entry["versions"]:
                    self.assertTrue(version["version"])
                    self.assertEqual(version["source"]["type"], "git")
                    self.assertEqual(
                        version["source"]["url"],
                        "https://github.com/storious/agentkube.git",
                    )
                    self.assertEqual(
                        version["source"]["ref"],
                        f"{entry['id']}-v{version['version']}",
                    )

    def test_plugins_are_v2_and_documented(self) -> None:
        manifests = sorted((ROOT / "plugins").glob("*/plugin.json"))
        self.assertEqual(
            [path.parent.name for path in manifests], ["coordinator", "web-search"]
        )
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            with self.subTest(plugin=manifest["name"]):
                self.assertEqual(manifest["format"], "agul/plugin/v2")
                self.assertTrue(manifest["command"])
                self.assertTrue(manifest["tools"])
                self.assertTrue((manifest_path.parent / "README.md").is_file())

    def test_coordinator_version_is_consistent_across_source_and_prepared_artifacts(self) -> None:
        plugin = json.loads(
            (ROOT / "plugins" / "coordinator" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        snapshot = json.loads(
            (
                ROOT
                / "starters"
                / "self-maintainer"
                / ".agents"
                / "runtime"
                / "snapshot.json"
            ).read_text(encoding="utf-8")
        )
        snapshot_entry = next(
            entry for entry in snapshot["resources"]["plugins"]
            if entry["id"] == "coordinator"
        )
        source = (ROOT / "plugins" / "coordinator" / "coordinator.py").read_text(
            encoding="utf-8"
        )
        client_version = re.search(
            r'^COORDINATOR_VERSION = "([^"]+)"$', source, re.MULTILINE
        )

        self.assertIsNotNone(client_version)
        versions = {
            plugin["version"],
            snapshot_entry["version"],
            client_version.group(1),
        }
        self.assertEqual(versions, {plugin["version"]})

    def test_web_search_and_starter_versions_match_prepared_artifacts(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        catalog_by_id = {entry["id"]: entry for entry in catalog["entries"]}
        starter_root = ROOT / "starters" / "self-maintainer" / ".agents"
        starter = json.loads((starter_root / "package.json").read_text(encoding="utf-8"))
        snapshot = json.loads(
            (starter_root / "runtime" / "snapshot.json").read_text(encoding="utf-8")
        )
        web_search = json.loads(
            (ROOT / "plugins" / "web-search" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        web_search_source = (
            ROOT / "plugins" / "web-search" / "web_search.py"
        ).read_text(encoding="utf-8")
        implementation_version = re.search(
            r'^PLUGIN_VERSION = "([^"]+)"$', web_search_source, re.MULTILINE
        )
        snapshot_plugins = {
            entry["id"]: entry for entry in snapshot["resources"]["plugins"]
        }

        self.assertIsNotNone(implementation_version)
        self.assertEqual(
            {
                web_search["version"],
                catalog_by_id["web-search"]["versions"][-1]["version"],
                snapshot_plugins["web-search"]["version"],
                implementation_version.group(1),
            },
            {web_search["version"]},
        )
        self.assertEqual(
            {
                starter["version"],
                snapshot["package"]["version"],
            },
            {starter["version"]},
        )

    def test_self_maintainer_starter_is_directly_composable(self) -> None:
        root = ROOT / "starters" / "self-maintainer" / ".agents"
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        pools = json.loads((root / "pools.json").read_text(encoding="utf-8"))

        self.assertEqual(package["format"], "agulater/package/v2")
        self.assertEqual(package["id"], "self-maintainer")
        self.assertEqual(
            {plugin["id"] for plugin in package["resources"]["plugins"]},
            {"coordinator", "web-search"},
        )
        self.assertEqual(len(package["resources"]["packages"]), 4)
        for resource in package["resources"]["packages"]:
            self.assertTrue(
                (root / resource["path"] / "package.json").resolve().is_file()
            )
        self.assertEqual(pools["format"], "agulater/pools/v2")
        self.assertEqual(pools["default_pool"], "deepseek")
        pools_by_id = {pool["id"]: pool for pool in pools["pools"]}
        self.assertEqual(
            set(pools_by_id),
            {"deepseek", "glm-coding", "codex-account", "local-example"},
        )
        pool = pools_by_id["deepseek"]
        self.assertEqual(pool["engine"], "native")
        self.assertEqual(
            pool["endpoint"], "https://api.deepseek.com/chat/completions"
        )
        self.assertEqual(pool["model"], "deepseek-v4-flash")
        glm = pools_by_id["glm-coding"]
        self.assertEqual(glm["provider"], "glm")
        self.assertEqual(glm["model"], "glm-4.7")
        self.assertEqual(
            pools_by_id["local-example"]["endpoint"],
            "http://127.0.0.1:51100/v1/chat/completions",
        )
        self.assertEqual(pools_by_id["local-example"]["reasoning_effort"], "medium")
        account_pool = pools_by_id["codex-account"]
        self.assertEqual(account_pool["engine"], "codex")
        self.assertEqual(account_pool["max_concurrency"], 1)
        self.assertNotIn("provider", account_pool)
        self.assertNotIn("endpoint", account_pool)
        self.assertNotIn("reasoning_effort", account_pool)

    def test_manual_acceptance_generates_local_pool_from_environment(self) -> None:
        checklist = (ROOT / "docs" / "acceptance" / "maintainer-runbook.md").read_text(
            encoding="utf-8"
        )

        self.assertFalse(
            (ROOT / "docs" / "acceptance" / "pools.local-deepseek-codex.json").exists()
        )
        self.assertIn("$env:AGUL_ACCEPTANCE_LOCAL_ENDPOINT", checklist)
        self.assertIn("$env:AGUL_ACCEPTANCE_LOCAL_MODEL", checklist)
        self.assertIn('format = "agulater/pools/v2"', checklist)
        self.assertIn('id = "local-default"', checklist)
        self.assertIn('id = "deepseek-subagent"', checklist)
        self.assertIn('id = "codex-account"', checklist)
        self.assertIn('api_key_env = "DEEPSEEK_API_KEY"', checklist)
        self.assertNotIn("pools.local-deepseek-codex.json", checklist)

    def test_tracked_public_text_has_no_private_acceptance_evidence(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split("\0")
        text_suffixes = {
            ".json",
            ".md",
            ".ps1",
            ".py",
            ".rs",
            ".sh",
            ".toml",
            ".txt",
            ".yaml",
            ".yml",
        }
        forbidden = {
            "private IPv4 address": re.compile(
                r"(?<![\d.])(?:"
                r"10(?:\.\d{1,3}){3}|"
                r"192\.168(?:\.\d{1,3}){2}|"
                r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
                r")(?![\d.])"
            ),
            "host-specific Windows path": re.compile(
                r"\b[A-Za-z]:\\(?:Users|Projects)\\", re.IGNORECASE
            ),
            "persisted Agul session id": re.compile(r"\b\d{18,}-\d+-\d+\b"),
            "upstream account thread id": re.compile(
                r"\b01[a-f0-9]{6}-[a-f0-9-]{20,}\b", re.IGNORECASE
            ),
            "account plan detail": re.compile(
                r"\bChatGPT\s+(?:Plus|Pro|Team|Enterprise)\b", re.IGNORECASE
            ),
            "legacy Agulater repository identity": re.compile(
                r"(?:storious/)?agent" + r"-playbook", re.IGNORECASE
            ),
        }

        findings: list[str] = []
        for relative in tracked:
            if not relative:
                continue
            path = ROOT / relative
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            content = path.read_text(encoding="utf-8")
            for label, pattern in forbidden.items():
                if pattern.search(content):
                    findings.append(f"{relative}: {label}")

        self.assertEqual(findings, [])

    def test_self_maintainer_runtime_matches_its_sources(self) -> None:
        runtime = ROOT / "starters" / "self-maintainer" / ".agents" / "runtime"
        registry = json.loads(
            (runtime / "specialists.json").read_text(encoding="utf-8")
        )
        specialists = {entry["id"]: entry for entry in registry["specialists"]}

        self.assertEqual(set(specialists), SPECIALIST_IDS)
        for specialist_id, entry in specialists.items():
            with self.subTest(specialist=specialist_id):
                source = ROOT / "agents" / specialist_id / ".agents"
                harness = json.loads(
                    (source / "harness.json").read_text(encoding="utf-8")
                )
                package = json.loads(
                    (source / "package.json").read_text(encoding="utf-8")
                )
                context = package["resources"]["contexts"][0]
                compiled_instructions = (
                    runtime / Path(entry["launch_path"]).parent / "instructions.md"
                ).read_text(encoding="utf-8")
                compiled_context = (
                    runtime
                    / Path(entry["launch_path"]).parent
                    / "resources"
                    / "contexts"
                    / f"{context['id']}{Path(context['path']).suffix}"
                )

                self.assertEqual(entry["version"], package["version"])
                self.assertEqual(entry["defaults"], harness["defaults"])
                self.assertEqual(compiled_instructions.count("<agul-handoff"), 1)
                self.assertIn(
                    "evidence, changes, verification, risks, and next_steps "
                    "must each be JSON arrays",
                    compiled_instructions,
                )
                self.assertIn(
                    "do not narrate plans, count rounds or tool calls, restate "
                    "gathered evidence, or draft the final answer",
                    compiled_instructions,
                )
                self.assertIn(
                    "If space is tight, omit optional prose and optional handoff "
                    "fields, then emit the minimal truthful handoff immediately",
                    compiled_instructions,
                )
                self.assertIn(
                    "Never omit the handoff or claim work that was not completed",
                    compiled_instructions,
                )
                self.assertEqual(
                    compiled_context.read_text(encoding="utf-8"),
                    (source / context["path"]).read_text(encoding="utf-8"),
                )

        plugin_files = {
            "coordinator": ("plugin.json", "coordinator.py", "README.md"),
            "web-search": ("plugin.json", "web_search.py", "README.md"),
        }
        for plugin_id, names in plugin_files.items():
            compiled_plugin = runtime / "resources" / "plugins" / plugin_id
            source_plugin = ROOT / "plugins" / plugin_id
            for name in names:
                with self.subTest(plugin=plugin_id, plugin_file=name):
                    self.assertEqual(
                        (compiled_plugin / name).read_text(encoding="utf-8"),
                        (source_plugin / name).read_text(encoding="utf-8"),
                    )

    def test_checked_in_schemas_are_valid_json(self) -> None:
        schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
        self.assertTrue(schemas)
        for path in schemas:
            with self.subTest(schema=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    value["$schema"], "https://json-schema.org/draft/2020-12/schema"
                )


if __name__ == "__main__":
    unittest.main()
