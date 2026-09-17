from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PROJECT_ROOT / "scripts" / "codebuddy_accounts.py"

# 测试目录放在工作区内，而不是系统的 %TEMP%。
# 受限环境（沙箱、被策略拦截的临时目录）会对 %TEMP% 直接拒绝写入，
# 那会让每个用例都死在建目录上，掩盖真正的回归。
TEST_TMP_ROOT = PROJECT_ROOT / ".tmp" / "test-codebuddy-accounts"


def make_temp_dir(case: unittest.TestCase) -> Path:
    """建一个工作区内的临时目录，并在用例结束时尽力清理。

    受限环境（DSH 沙箱）允许在工作区内建目录，但对新目录下面的 *再加一层*
    子目录会返回 ``WinError 5``。所以调用方必须把这里返回的目录当作一个
    扁平工作区来用：快照库、导出文件等都用 ``make_temp_siblings`` 拿同级目录，
    而不是在这个目录里再 mkdir。
    """
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{case._testMethodName}-", dir=str(TEST_TMP_ROOT)))

    def cleanup() -> None:
        shutil.rmtree(root, ignore_errors=True)

    case.addCleanup(cleanup)
    return root


def make_temp_siblings(case: unittest.TestCase, *names: str) -> list[Path]:
    """为用例建一组互不嵌套的同级目录（快照库、导出目录等）。"""
    paths: list[Path] = []
    for name in names:
        base = Path(tempfile.mkdtemp(prefix=f"{case._testMethodName}-{name}-", dir=str(TEST_TMP_ROOT)))
        paths.append(base)

        def cleanup(target: Path = base) -> None:
            shutil.rmtree(target, ignore_errors=True)

        case.addCleanup(cleanup)
    return paths


def load_tool():
    """把 CLI 脚本当模块导入（它不在包内，只能按路径加载）。"""
    spec = importlib.util.spec_from_file_location("codebuddy_accounts", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["codebuddy_accounts"] = module
    spec.loader.exec_module(module)
    return module


tool = load_tool()


def fake_jwt(claims: dict) -> str:
    def segment(obj: object) -> str:
        raw = json.dumps(obj).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{segment({'alg': 'RS256', 'typ': 'JWT'})}.{segment(claims)}.signature"


def make_credential(uid: str, nickname: str, *, access_ttl_s: int = 3600, refresh_ttl_s: int = 7200) -> dict:
    now_ms = time.time() * 1000
    return {
        "auth": {
            "accessToken": fake_jwt({"preferred_username": f"user-{uid[:4]}", "exp": int(time.time()) + access_ttl_s}),
            "expiresAt": now_ms + access_ttl_s * 1000,
            "refreshToken": fake_jwt({"exp": int(time.time()) + refresh_ttl_s}),
            "refreshExpiresAt": now_ms + refresh_ttl_s * 1000,
            "domain": "www.codebuddy.cn",
        },
        "account": {"uid": uid, "nickname": nickname, "uin": "100000000001"},
    }


class CredentialValidationTests(unittest.TestCase):
    """凭据形状校验：坏文件必须被挡下，而不是写进凭据文件把用户登出。"""

    def test_accepts_well_formed_credential(self) -> None:
        credential = tool.normalize_credential(make_credential("uid-1", "甲"))
        self.assertEqual(credential["account"]["uid"], "uid-1")
        self.assertEqual(credential["account"]["nickname"], "甲")

    def test_rejects_missing_auth_section(self) -> None:
        with self.assertRaises(tool.ToolError):
            tool.normalize_credential({"account": {"uid": "uid-1"}})

    def test_rejects_missing_uid(self) -> None:
        payload = make_credential("uid-1", "甲")
        del payload["account"]["uid"]
        with self.assertRaises(tool.ToolError):
            tool.normalize_credential(payload)

    def test_rejects_credential_missing_required_auth_fields(self) -> None:
        for field in tool.REQUIRED_AUTH_FIELDS:
            with self.subTest(field=field):
                payload = make_credential("uid-1", "甲")
                del payload["auth"][field]
                with self.assertRaises(tool.ToolError):
                    tool.normalize_credential(payload)

    def test_drops_empty_optional_account_fields(self) -> None:
        """插件把空字符串当作“不存在”，快照必须保持一致，否则 UI 会渲染空行。"""
        payload = make_credential("uid-1", "甲")
        payload["account"]["uin"] = ""
        payload["account"]["enterpriseId"] = ""
        credential = tool.normalize_credential(payload)
        self.assertNotIn("uin", credential["account"])
        self.assertNotIn("enterpriseId", credential["account"])

    def test_does_not_copy_unknown_fields(self) -> None:
        """只保留插件认识的字段，避免把无关敏感内容复制进快照库。"""
        payload = make_credential("uid-1", "甲")
        payload["secretExtra"] = "should-not-survive"
        payload["auth"]["cookie"] = "should-not-survive"
        credential = tool.normalize_credential(payload)
        self.assertNotIn("secretExtra", credential)
        self.assertNotIn("cookie", credential["auth"])


class CredentialFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(self)

    def test_round_trip_write_and_read(self) -> None:
        path = self.root / "auth.json"
        original = tool.normalize_credential(make_credential("uid-1", "甲"))
        tool.write_credential_file(path, original)
        self.assertEqual(tool.load_credential_file(path), original)

    def test_reads_file_with_utf8_bom(self) -> None:
        """Windows 编辑器与 PowerShell 会写 BOM；带 BOM 不等于坏文件。"""
        path = self.root / "auth.json"
        payload = make_credential("uid-1", "甲")
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(tool.load_credential_file(path)["account"]["uid"], "uid-1")

    def test_written_file_has_no_bom(self) -> None:
        path = self.root / "auth.json"
        tool.write_credential_file(path, tool.normalize_credential(make_credential("uid-1", "甲")))
        self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_write_is_atomic_leaving_no_temp_files(self) -> None:
        path = self.root / "auth.json"
        tool.write_credential_file(path, tool.normalize_credential(make_credential("uid-1", "甲")))
        leftovers = [item.name for item in self.root.iterdir() if item.name != "auth.json"]
        self.assertEqual(leftovers, [], f"原子写入留下了临时文件：{leftovers}")

    def test_write_replaces_existing_file_completely(self) -> None:
        path = self.root / "auth.json"
        first = tool.normalize_credential(make_credential("uid-1", "甲"))
        second = tool.normalize_credential(make_credential("uid-2", "乙乙乙乙乙乙乙乙乙乙"))
        tool.write_credential_file(path, first)
        tool.write_credential_file(path, second)
        self.assertEqual(tool.load_credential_file(path)["account"]["uid"], "uid-2")

    def test_corrupt_json_reports_tool_error(self) -> None:
        path = self.root / "auth.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(tool.ToolError):
            tool.load_credential_file(path)

    def test_missing_file_reports_tool_error(self) -> None:
        with self.assertRaises(tool.ToolError):
            tool.load_credential_file(self.root / "absent.json")


class DescribeCredentialTests(unittest.TestCase):
    def test_reports_expired_refresh_token(self) -> None:
        info = tool.describe_credential(
            tool.normalize_credential(make_credential("uid-1", "甲", access_ttl_s=-10, refresh_ttl_s=-5))
        )
        self.assertTrue(info["access_expired"])
        self.assertTrue(info["refresh_expired"])

    def test_fresh_access_token_is_not_expired(self) -> None:
        info = tool.describe_credential(tool.normalize_credential(make_credential("uid-1", "甲")))
        self.assertFalse(info["access_expired"])
        self.assertFalse(info["refresh_expired"])

    def test_decodes_username_from_access_token(self) -> None:
        info = tool.describe_credential(tool.normalize_credential(make_credential("abcd1234", "甲")))
        self.assertEqual(info["username"], "user-abcd")

    def test_survives_unparseable_access_token(self) -> None:
        """令牌不是 JWT 时也必须能展示，不能因为解不开就崩。"""
        payload = make_credential("uid-1", "甲")
        payload["auth"]["accessToken"] = "not-a-jwt"
        info = tool.describe_credential(tool.normalize_credential(payload))
        self.assertEqual(info["username"], "")


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = tool.SnapshotStore(make_temp_siblings(self, "store")[0])

    def test_add_and_list_round_trip(self) -> None:
        self.store.add(tool.normalize_credential(make_credential("uid-1", "甲")), "甲")
        self.store.add(tool.normalize_credential(make_credential("uid-2", "乙")), "乙")
        names = self.store.list_names()
        self.assertEqual(len(names), 2)
        self.assertTrue(all(self.store.snapshot_path(name).exists() for name in names))

    def test_readding_same_label_replaces_instead_of_duplicating(self) -> None:
        credential = tool.normalize_credential(make_credential("uid-1", "甲"))
        self.store.add(credential, "甲")
        self.store.add(credential, "甲")
        self.assertEqual(len(self.store.list_names()), 1)

    def test_different_accounts_same_nickname_do_not_collide(self) -> None:
        """文件名带 uid 前缀，同名账号不能互相覆盖。"""
        self.store.add(tool.normalize_credential(make_credential("uid-1", "同名")), "同名")
        self.store.add(tool.normalize_credential(make_credential("uid-2", "同名")), "同名")
        self.assertEqual(len(self.store.list_names()), 2)

    def test_remove_deletes_snapshot_and_index_entry(self) -> None:
        self.store.add(tool.normalize_credential(make_credential("uid-1", "甲")), "甲")
        name = self.store.list_names()[0]
        self.store.remove(name)
        self.assertEqual(self.store.list_names(), [])
        self.assertFalse(self.store.snapshot_path(name).exists())

    def test_index_self_heals_after_manual_deletion(self) -> None:
        """手工删掉快照文件后，list 不能继续报一个不存在的条目。"""
        self.store.add(tool.normalize_credential(make_credential("uid-1", "甲")), "甲")
        self.store.snapshot_path(self.store.list_names()[0]).unlink()
        self.assertEqual(self.store.list_names(), [])

    def test_unindexed_files_are_still_discovered(self) -> None:
        """散落在目录里的快照不能被静默忽略。"""
        self.store.ensure()
        tool.write_credential_file(
            self.store.snapshot_path("orphan.json"),
            tool.normalize_credential(make_credential("uid-9", "孤儿")),
        )
        self.assertIn("orphan.json", self.store.list_names())


class ResolveTests(unittest.TestCase):
    """解析必须接受用户在 `list` 里看得到的东西：序号、昵称、UID。"""

    def setUp(self) -> None:
        self.store = tool.SnapshotStore(make_temp_siblings(self, "store")[0])
        self.store.add(tool.normalize_credential(make_credential("3c5aa09c-8725", "時肆")), "主号")
        self.store.add(tool.normalize_credential(make_credential("aaaaaaaa-bbbb", "测试二号")), "备份号")

    def test_resolve_by_sequence_number(self) -> None:
        names = self.store.list_names()
        self.assertEqual(self.store.resolve("1"), names[0])
        self.assertEqual(self.store.resolve("2"), names[1])

    def test_resolve_by_nickname(self) -> None:
        """回归：list 显示昵称，所以昵称必须能直接命中。"""
        self.assertEqual(self.store.resolve("時肆"), self.store.list_names()[0])
        self.assertEqual(self.store.resolve("测试二号"), self.store.list_names()[1])

    def test_resolve_by_full_filename(self) -> None:
        name = self.store.list_names()[1]
        self.assertEqual(self.store.resolve(name), name)

    def test_resolve_by_filename_stem(self) -> None:
        name = self.store.list_names()[1]
        self.assertEqual(self.store.resolve(Path(name).stem), name)

    def test_resolve_by_uid_prefix(self) -> None:
        self.assertEqual(self.store.resolve("aaaaaaaa"), self.store.list_names()[1])

    def test_resolve_by_partial_nickname(self) -> None:
        self.assertEqual(self.store.resolve("测试"), self.store.list_names()[1])

    def test_out_of_range_sequence_reports_error(self) -> None:
        with self.assertRaises(tool.ToolError) as caught:
            self.store.resolve("99")
        self.assertIn("超出范围", str(caught.exception))

    def test_unknown_key_reports_error(self) -> None:
        with self.assertRaises(tool.ToolError) as caught:
            self.store.resolve("不存在的账号")
        self.assertIn("没有匹配", str(caught.exception))

    def test_empty_store_reports_error(self) -> None:
        empty = tool.SnapshotStore(make_temp_siblings(self, "empty")[0])
        with self.assertRaises(tool.ToolError):
            empty.resolve("1")


class CliEndToEndTests(unittest.TestCase):
    """走完整 CLI：save -> import -> use -> status，并确认真的换了账号。"""

    def setUp(self) -> None:
        # 三个同级目录：凭据所在目录、快照库、以及存放待导入文件的目录。
        # 受限环境不允许嵌套 mkdir，所以工具的备份目录（凭据文件旁边）也只能
        # 落在已经存在的扁平目录里。
        self.root, self.store_dir, self.export_dir = make_temp_siblings(
            self, "work", "store", "exports",
        )
        self.auth_path = self.root / "codebuddy-auth.json"

        self._saved_env = {
            key: os.environ.get(key)
            for key in ("DSH_CODEBUDDY_AUTH_FILE", "CODEBUDDY_ACCOUNTS_DIR", "DSH_HOME")
        }
        os.environ["DSH_CODEBUDDY_AUTH_FILE"] = str(self.auth_path)
        os.environ["CODEBUDDY_ACCOUNTS_DIR"] = str(self.store_dir)

        def restore() -> None:
            for key, value in self._saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)

        self.live = make_credential("3c5aa09c-live", "時肆")
        tool.write_credential_file(self.auth_path, tool.normalize_credential(self.live))

    def run_cli(self, *argv: str) -> int:
        return tool.main(list(argv))

    def live_uid(self) -> str:
        return tool.load_credential_file(self.auth_path)["account"]["uid"]

    def test_status_reports_live_account(self) -> None:
        self.assertEqual(self.run_cli("status"), 0)

    def test_save_then_use_round_trip(self) -> None:
        self.assertEqual(self.run_cli("save", "主号"), 0)
        self.assertEqual(len(tool.SnapshotStore(self.store_dir).list_names()), 1)

    def test_import_then_switch_changes_live_credential(self) -> None:
        other = self.export_dir / "other.json"
        tool.write_credential_file(other, tool.normalize_credential(make_credential("bbbbbbbb-other", "二号")))

        self.assertEqual(self.run_cli("save", "主号"), 0)
        self.assertEqual(self.run_cli("import", str(other)), 0)
        self.assertEqual(self.run_cli("use", "二号"), 0)
        self.assertEqual(self.live_uid(), "bbbbbbbb-other")

        # 切回去，确认双向都成立。
        self.assertEqual(self.run_cli("use", "時肆"), 0)
        self.assertEqual(self.live_uid(), "3c5aa09c-live")

    def test_switch_creates_backup_of_previous_credential(self) -> None:
        other = self.export_dir / "other.json"
        tool.write_credential_file(other, tool.normalize_credential(make_credential("bbbbbbbb-other", "二号")))
        self.run_cli("import", str(other))
        self.run_cli("use", "二号")
        backups = list((self.root / "codebuddy-auth-backups").glob("*.json"))
        self.assertTrue(backups, "切换前必须留下原凭据备份")
        restored = tool.load_credential_file(backups[0])
        self.assertEqual(restored["account"]["uid"], "3c5aa09c-live")

    def test_import_rejects_missing_file(self) -> None:
        self.assertEqual(self.run_cli("import", str(self.root / "absent.json")), 1)

    def test_import_rejects_invalid_credential(self) -> None:
        bad = self.export_dir / "bad.json"
        bad.write_text(json.dumps({"account": {"uid": "x"}}), encoding="utf-8")
        self.assertEqual(self.run_cli("import", str(bad)), 1)

    def test_use_unknown_account_fails_without_touching_live_file(self) -> None:
        self.run_cli("save", "主号")
        self.assertEqual(self.run_cli("use", "不存在"), 1)
        self.assertEqual(self.live_uid(), "3c5aa09c-live")

    def test_remove_keeps_live_credential_intact(self) -> None:
        self.run_cli("save", "主号")
        self.assertEqual(self.run_cli("remove", "主号"), 0)
        self.assertEqual(self.live_uid(), "3c5aa09c-live")

    def test_import_accepts_directory(self) -> None:
        tool.write_credential_file(
            self.export_dir / "a.json",
            tool.normalize_credential(make_credential("cccccccc-a", "甲")),
        )
        self.assertEqual(self.run_cli("import", str(self.export_dir)), 0)
        self.assertEqual(len(tool.SnapshotStore(self.store_dir).list_names()), 1)

    def test_import_accepts_info_extension(self) -> None:
        """回归：codebuddy2api 的账号文件后缀是 .info，目录导入必须认。

        它的字段与本工具完全兼容，只是后缀不同；早期只找 *.json，
        导致直接导入该目录时一个账号都找不到。
        """
        payload = make_credential("dddddddd-info", "info号")
        (self.export_dir / "dddddddd.info").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8",
        )
        self.assertEqual(self.run_cli("import", str(self.export_dir)), 0)
        store = tool.SnapshotStore(self.store_dir)
        self.assertEqual(len(store.list_names()), 1)
        self.assertEqual(store.read(store.list_names()[0])["account"]["uid"], "dddddddd-info")

    def test_directory_import_skips_unrelated_json(self) -> None:
        """账单、模型目录等 JSON 混在同一目录里时必须被跳过，而不是让导入失败。"""
        (self.export_dir / "credits-ledger.json").write_text('{"total": 1}', encoding="utf-8")
        tool.write_credential_file(
            self.export_dir / "real.json",
            tool.normalize_credential(make_credential("eeeeeeee-real", "真号")),
        )
        self.assertEqual(self.run_cli("import", str(self.export_dir)), 0)
        self.assertEqual(len(tool.SnapshotStore(self.store_dir).list_names()), 1)

    def test_saved_snapshot_is_independent_of_live_file(self) -> None:
        """切换后快照不能被就地改写：它必须保持自己的账号。"""
        other = self.export_dir / "other.json"
        tool.write_credential_file(other, tool.normalize_credential(make_credential("bbbbbbbb-other", "二号")))
        self.run_cli("save", "主号")
        self.run_cli("import", str(other))
        self.run_cli("use", "二号")

        store = tool.SnapshotStore(self.store_dir)
        primary = next(name for name in store.list_names() if "主号" in name)
        self.assertEqual(store.read(primary)["account"]["uid"], "3c5aa09c-live")


if __name__ == "__main__":
    unittest.main()
