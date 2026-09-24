from astroswarm_linux import cli, headless_config, platform_info


def test_cli_status_prints_machine_id(capsys, monkeypatch):
    monkeypatch.setattr(platform_info, "machine_id", lambda: "MACHINE-1")
    assert cli.main(["status"]) == 0
    assert "MACHINE-1" in capsys.readouterr().out


def test_cli_install_writes_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    assert cli.main(["install", "--port", "7890"]) == 0
    cfg = headless_config.load()
    assert cfg["port"] == 7890
    assert "配置已写入" in capsys.readouterr().out
