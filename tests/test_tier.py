"""Tier classifier tests. Each test names one classification axis."""
import pytest
from bin import tier


def test_silent_tier_for_tmp_path():
    t, _, na = tier.classify("touch /tmp/foo")
    assert t == "silent"
    assert na is None


def test_silent_tier_for_no_path():
    t, _, na = tier.classify("echo hello")
    assert t == "silent"
    assert na is None


def test_silent_tier_for_dev_null():
    t, _, na = tier.classify("cat foo > /dev/null")
    assert t == "silent"


def test_repo_tier_for_relative_path():
    t, _, na = tier.classify("touch myfile.txt")
    assert t == "repo"


def test_repo_tier_for_dot_relative_path():
    t, _, na = tier.classify("mkdir -p ./src/widgets")
    assert t == "repo"


def test_host_tier_for_etc_path():
    t, _, na = tier.classify("touch /etc/foo.conf")
    assert t == "host"


def test_host_tier_for_usr_path():
    t, _, na = tier.classify("cp x /usr/local/bin/y")
    assert t == "host"


def test_host_tier_for_var_path_excludes_var_tmp():
    t_var, _, _ = tier.classify("touch /var/log/foo.log")
    assert t_var == "host"
    t_var_tmp, _, _ = tier.classify("touch /var/tmp/foo")
    assert t_var_tmp == "silent"


def test_host_tier_for_systemd_unit():
    t, _, na = tier.classify("touch /etc/systemd/system/foo.service")
    assert t == "host"


def test_network_tier_for_curl():
    t, _, na = tier.classify("curl https://example.com")
    assert t == "network"


def test_network_tier_for_wget():
    t, _, na = tier.classify("wget https://example.com/file")
    assert t == "network"


def test_network_tier_for_git_push():
    t, _, na = tier.classify("git push origin master")
    assert t == "network"


def test_network_tier_for_gh_command():
    t, _, na = tier.classify("gh pr list")
    assert t == "network"


def test_never_autonomous_pip_install_overrides_silent():
    t, _, na = tier.classify("pip install requests")
    assert na == "dependency-add: pip install"


def test_never_autonomous_chmod_in_silent_tier():
    t, _, na = tier.classify("chmod 644 /tmp/foo")
    assert t == "silent"
    assert na == "permission-change: chmod"


def test_never_autonomous_apt_install():
    t, _, na = tier.classify("apt-get install -y nginx")
    assert na == "dependency-add: apt-get install"


def test_never_autonomous_drop_table():
    t, _, na = tier.classify("psql -c 'DROP TABLE users;'")
    assert na == "schema-mutation: DROP TABLE"


def test_never_autonomous_iptables():
    t, _, na = tier.classify("iptables -A INPUT -j DROP")
    assert na == "permission-change: iptables"


def test_never_autonomous_paid_api_openai():
    t, _, na = tier.classify("curl https://api.openai.com/v1/chat/completions")
    assert na == "paid-api-call: api.openai.com"


def test_never_autonomous_gh_pr_create():
    t, _, na = tier.classify("gh pr create --title foo")
    assert na == "external-state-network: gh pr create"


def test_classify_returns_tuple_shape():
    result = tier.classify("touch /tmp/foo")
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert isinstance(result[0], str)
    assert isinstance(result[1], list)
    assert result[2] is None or isinstance(result[2], str)


def test_should_halt_silent_returns_false():
    assert tier.should_halt("silent", None) is False


def test_should_halt_repo_returns_false():
    assert tier.should_halt("repo", None) is False


def test_should_halt_host_returns_true():
    assert tier.should_halt("host", None) is True


def test_should_halt_network_returns_true():
    assert tier.should_halt("network", None) is True


def test_should_halt_with_never_autonomous_overrides_silent():
    assert tier.should_halt("silent", "dependency-add: pip install") is True


def test_should_halt_with_never_autonomous_overrides_repo():
    assert tier.should_halt("repo", "permission-change: chmod") is True


# --- Bug 1: rm -rf ---

def test_never_autonomous_rm_rf():
    t, _, na = tier.classify("rm -rf /tmp/foo")
    assert na == "destructive-delete: rm -rf"


def test_never_autonomous_rm_rf_root():
    t, _, na = tier.classify("rm -rf /")
    assert na is not None
    assert "destructive-delete" in na


def test_should_halt_on_rm_rf():
    t, _, na = tier.classify("rm -rf /home/foo/")
    assert tier.should_halt(t, na) is True


# --- Bug 2: sudo ---

def test_never_autonomous_sudo():
    t, _, na = tier.classify("sudo systemctl restart nginx")
    assert na == "permission-change: sudo"


def test_sudo_curl_classified_network():
    t, _, na = tier.classify("sudo curl https://example.com")
    assert t == "network"
    assert na == "permission-change: sudo"


def test_should_halt_on_sudo_anywhere():
    t, _, na = tier.classify("sudo touch /tmp/x")
    assert tier.should_halt(t, na) is True


# --- Bug 3: quoted-string false positives ---

def test_chmod_inside_commit_message_does_not_match():
    t, _, na = tier.classify('git commit -m "fix chmod regression"')
    assert na is None


def test_drop_table_in_psql_still_matches():
    t, _, na = tier.classify("psql -c 'DROP TABLE users;'")
    assert na == "schema-mutation: DROP TABLE"


# --- Bug 4: extensionless paths with slash ---

def test_repo_tier_for_extensionless_path_with_slash():
    t, _, na = tier.classify("touch src/widgets/foo")
    assert t == "repo"
