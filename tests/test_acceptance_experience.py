from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from docs.acceptance import experience, prepare_experience


class ExperienceTests(unittest.TestCase):
    def ready(self, home: Path) -> dict:
        return {
            "agul": str(home / "bin/agul"),
            "agulater": str(home / "bin/agulater"),
            "candidate": {"versions": {"agul": "test"}, "repositories": {}},
        }

    def test_routes_keep_real_tui_and_glm_coding_plan(self):
        home = Path(tempfile.gettempdir()) / "experience-test"
        ready = self.ready(home)
        for scene in experience.SCENES:
            command = experience.chat_command(ready, home, scene)
            self.assertNotIn("--prompt", command)
            self.assertNotIn("--json", command)
            self.assertIn("--launch", command)
            self.assertIn("--state-dir", command)
            if scene in {"2", "4", "5"}:
                self.assertEqual(command[command.index("--provider") + 1], "glm")
                self.assertNotIn("--base-url", command)
        for option in ("--continue", "--resume"):
            command = experience.chat_command(ready, home, "3", option)
            self.assertIn(option, command)
            self.assertNotIn("--engine", command)
            self.assertNotIn("--provider", command)

    def test_child_keeps_account_home_but_drops_ambient_native_route(self):
        home = Path(tempfile.gettempdir()) / "experience-test"
        with patch.dict(
            os.environ,
            {
                "HOME": "real-home",
                "CODEX_HOME": "real-codex",
                "AGUL_BASE_URL": "http://127.0.0.1/v1",
            },
        ):
            env = experience.child_env(self.ready(home), home)
            self.assertEqual(env["HOME"], "real-home")
            self.assertEqual(env["CODEX_HOME"], "real-codex")
            self.assertNotIn("AGUL_BASE_URL", env)
            self.assertIn("AGUL_BASE_URL", os.environ)
            self.assertEqual(env["AGUL_STATE_DIR"], str(home / "state"))

    def test_ctrl_c_does_not_leave_a_live_tui_under_the_menu(self):
        home = Path(tempfile.gettempdir()) / "experience-test"
        process = Mock()
        process.wait.side_effect = [KeyboardInterrupt, 0]
        with patch.object(
            experience.subprocess, "Popen", return_value=process
        ) as start:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(experience.run_chat(self.ready(home), home, "1"), 0)
        self.assertEqual(process.wait.call_count, 2)
        for option in ("stdin", "stdout", "stderr", "shell"):
            self.assertNotIn(option, start.call_args.kwargs)

    def test_menu_reuses_last_scene_without_building_or_installing(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with (
                patch.dict(os.environ, {"GLM_API_KEY": "test-only"}),
                patch("builtins.input", side_effect=["2", "6", "0"]),
                patch.object(experience, "run_chat", return_value=0) as chat,
                patch.object(experience, "record_result"),
                patch.object(prepare_experience, "prepare") as prepare,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                experience.menu(self.ready(home), home)
            self.assertEqual(chat.call_args_list[0].args[2:], ("2", None))
            self.assertEqual(chat.call_args_list[1].args[2:], ("2", "--continue"))
            self.assertEqual(experience.load_json(home / "last-scene.json"), "2")
            prepare.assert_not_called()

    def test_local_pool_defaults_and_no_local_does_not_block_other_scenes(self):
        with patch.dict(os.environ, {}, clear=True):
            missing = prepare_experience.make_pools({})
            self.assertEqual(missing["default_pool"], "deepseek-subagent")
            pools = prepare_experience.make_pools(
                {"endpoint": "http://127.0.0.1/v1", "model": "test"}
            )
        self.assertEqual(
            {p["id"] for p in pools["pools"]},
            {"local-default", "deepseek-subagent", "codex-account"},
        )
        local = pools["pools"][0]
        self.assertEqual(local["reasoning_effort"], "medium")
        self.assertEqual(local["context_window"], 32768)
        self.assertEqual(local["request_timeout_seconds"], 600)

    def test_refresh_never_resets_user_practice_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            prepare_experience.write_fixture(home, "calculator.py", "original")
            (home / "calculator.py").write_text("owner edit", encoding="utf-8")
            prepare_experience.write_fixture(home, "calculator.py", "original")
            self.assertEqual(
                (home / "calculator.py").read_text(encoding="utf-8"), "owner edit"
            )

    def test_exiting_successfully_does_not_record_a_manual_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with patch("builtins.input", return_value=""):
                experience.record_result(home, self.ready(home), "1", 0)
            self.assertFalse((home / "results.jsonl").exists())

    def test_owner_document_has_one_entry_instead_of_a_shell_runbook(self):
        text = (experience.ROOT / "docs/acceptance/README.md").read_text(
            encoding="utf-8"
        )
        self.assertLess(len(text.splitlines()), 80)
        self.assertIn("start.cmd", text)
        self.assertNotIn("ConvertFrom-Json", text)
        self.assertNotIn("Expand-Archive", text)


if __name__ == "__main__":
    unittest.main()
