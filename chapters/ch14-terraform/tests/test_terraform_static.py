"""AWS も terraform も要らない、ファイルだけの検査。"""
import re
import subprocess
import shutil
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "terraform"
TF = {p.name: p.read_text() for p in SRC.glob("*.tf")}


def test_state_backend_is_s3_encrypted_with_lockfile_and_no_hardcoded_names():
    text = TF["backend.tf"]
    assert 'backend "s3"' in text and "encrypt      = true" in text and "use_lockfile = true" in text
    assert "bucket" not in text  # 環境依存の値は backend.hcl で渡す
    assert "dynamodb_table" not in text  # 1.10 以降は不要


def test_backend_example_has_placeholder_not_a_real_account_id():
    ex = (SRC / "backend.hcl.example").read_text()
    assert "<AWSアカウントID>" in ex and not re.search(r"\d{12}", ex)


def test_no_secret_variable_or_literal_password_in_configuration():
    joined = "\n".join(TF.values())
    assert "db_password" not in joined
    assert not re.search(r'^\s*password\s*=', joined, re.M)
    assert "manage_master_user_password = true" in TF["rds.tf"]


def test_state_and_local_secrets_are_gitignored():
    ignored = (SRC / ".gitignore").read_text().split()
    for pat in (".terraform/", "*.tfstate", "*.tfstate.*", "*.tfplan", "backend.hcl", "terraform.tfvars"):
        assert pat in ignored
    assert ".terraform.lock.hcl" not in ignored  # ロックファイルはコミットする


def test_lock_file_is_committed_and_pins_aws_provider():
    lock = (SRC / ".terraform.lock.hcl").read_text()
    assert 'provider "registry.terraform.io/hashicorp/aws"' in lock and 'version     = "6.' in lock


def test_required_versions_are_pinned():
    text = TF["providers.tf"]
    assert 'version = "~> 6.0"' in text and 'required_version = ">= 1.10.0"' in text


def test_nat_is_off_by_default_so_forgetting_a_flag_costs_less():
    assert re.search(r'variable "enable_nat_gateway".*?default\s*=\s*false', TF["variables.tf"], re.S)


def test_no_security_group_opens_inbound_to_anywhere():
    for name, text in TF.items():
        for m in re.finditer(r"ingress_rule\".*?\n}\n", text, re.S):
            assert "0.0.0.0/0" not in m.group(0), name


@pytest.mark.skipif(not shutil.which("terraform"), reason="terraform が必要")
def test_terraform_fmt_is_clean():
    r = subprocess.run(["terraform", f"-chdir={SRC}", "fmt", "-check", "-recursive"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
