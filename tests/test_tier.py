"""Tier classifier tests. Each test names one classification axis."""
import pathlib
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


# --- v0.3.1 gap 6: systemctl service-state mutations ---

def test_never_autonomous_systemctl_start():
    _, _, na = tier.classify("systemctl start nginx")
    assert na == "service-state-mutation: systemctl"


def test_never_autonomous_systemctl_user_enable_now():
    _, _, na = tier.classify("systemctl --user enable --now spectre-smoke.service")
    assert na == "service-state-mutation: systemctl"


def test_never_autonomous_systemctl_restart():
    _, _, na = tier.classify("systemctl restart sshd")
    assert na == "service-state-mutation: systemctl"


def test_never_autonomous_systemctl_disable():
    _, _, na = tier.classify("systemctl --user disable spectre-smoke.service")
    assert na == "service-state-mutation: systemctl"


def test_systemctl_status_does_not_match():
    _, _, na = tier.classify("systemctl --user status spectre-smoke.service")
    assert na is None


def test_systemctl_inside_quoted_action_does_not_match():
    _, _, na = tier.classify("echo 'run: systemctl start nginx'")
    assert na is None


# --- v0.3.1 gap 6: loginctl linger ---

def test_never_autonomous_loginctl_enable_linger():
    _, _, na = tier.classify("loginctl enable-linger joncik")
    assert na == "session-policy-mutation: loginctl linger"


def test_never_autonomous_loginctl_disable_linger():
    _, _, na = tier.classify("loginctl disable-linger joncik")
    assert na == "session-policy-mutation: loginctl linger"


def test_loginctl_show_user_does_not_match():
    _, _, na = tier.classify("loginctl show-user joncik")
    assert na is None


# --- v0.3.1 gap 6: hostnamectl, timedatectl, sysctl ---

def test_never_autonomous_hostnamectl_set():
    _, _, na = tier.classify("hostnamectl set-hostname foo")
    assert na == "host-state-mutation: hostnamectl"


def test_never_autonomous_timedatectl_set():
    _, _, na = tier.classify("timedatectl set-timezone UTC")
    assert na == "host-state-mutation: timedatectl"


def test_never_autonomous_sysctl_write():
    _, _, na = tier.classify("sysctl -w net.ipv4.ip_forward=1")
    assert na == "kernel-state-mutation: sysctl write"


def test_sysctl_read_does_not_match():
    _, _, na = tier.classify("sysctl net.ipv4.ip_forward")
    assert na is None


# --- v0.3.1 gap 9: loopback URLs downgrade from network tier ---

def test_curl_loopback_127_is_silent():
    t, _, _ = tier.classify("curl http://127.0.0.1:8791/health -o /tmp/x.json")
    assert t == "silent"


def test_curl_loopback_localhost_is_silent():
    t, _, _ = tier.classify("curl http://localhost:8080/foo -o /tmp/y.json")
    assert t == "silent"


def test_curl_loopback_ipv6_is_silent():
    t, _, _ = tier.classify("curl http://[::1]:8000/foo -o /tmp/z.json")
    assert t == "silent"


def test_curl_rfc1918_is_silent():
    t, _, _ = tier.classify("curl http://192.168.0.1/admin -o /tmp/r.json")
    assert t == "silent"


def test_curl_public_url_remains_network():
    t, _, _ = tier.classify("curl https://api.example.com/v1/foo")
    assert t == "network"


def test_curl_with_variable_url_remains_network():
    t, _, _ = tier.classify("curl $UPSTREAM_URL/foo")
    assert t == "network"


def test_wget_loopback_is_silent():
    t, _, _ = tier.classify("wget http://127.0.0.1/foo -O /tmp/w")
    assert t == "silent"


def test_should_halt_consults_personal_rules_when_no_spec_lock(tmp_path, monkeypatch):
    """Personal rule downgrades a host-tier halt when the active spec's
    §8.1 doesn't touch the same paths."""
    from bin import personal_rules
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    personal_rules.reset_session_counter() if hasattr(personal_rules, "reset_session_counter") else None

    fp = tier.fingerprint_for_action(
        action="touch /etc/foo.conf",
        classifier_label="path '/etc/foo.conf' → host",
    )
    personal_rules.append_adoption(
        classifier_label="path '/etc/foo.conf' → host",
        fingerprint=fp,
        reason="I trust this",
    )

    result = tier.should_halt(
        tier_value="host",
        never_autonomous_match=None,
        action="touch /etc/foo.conf",
        reasons=["path '/etc/foo.conf' → host"],
        spec_locked_paths=frozenset(),  # empty — no §8.1 immunity
    )
    assert result is False


def test_should_halt_personal_rule_cannot_override_when_path_in_spec_lock(tmp_path, monkeypatch):
    """Personal rule for /etc/foo.conf cannot override a halt when the
    active spec's §8.1 has /etc/foo.conf in mutates/never-touches."""
    from bin import personal_rules
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    personal_rules.reset_session_counter() if hasattr(personal_rules, "reset_session_counter") else None

    fp = tier.fingerprint_for_action(
        action="touch /etc/foo.conf",
        classifier_label="path '/etc/foo.conf' → host",
    )
    personal_rules.append_adoption(
        classifier_label="path '/etc/foo.conf' → host",
        fingerprint=fp,
        reason="I trust this",
    )

    result = tier.should_halt(
        tier_value="host",
        never_autonomous_match=None,
        action="touch /etc/foo.conf",
        reasons=["path '/etc/foo.conf' → host"],
        spec_locked_paths=frozenset({"/etc/foo.conf"}),  # spec mandates halt
    )
    assert result is True


def test_should_halt_no_personal_rule_returns_default_for_host(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = tier.should_halt(
        tier_value="host",
        never_autonomous_match=None,
        action="touch /etc/foo.conf",
        reasons=["path '/etc/foo.conf' → host"],
        spec_locked_paths=frozenset(),
    )
    assert result is True


def test_should_halt_legacy_call_signature_still_works():
    """v0.4.0 callers passing only (tier_value, never_autonomous_match) must keep working."""
    result = tier.should_halt("host", None)
    assert result is True
