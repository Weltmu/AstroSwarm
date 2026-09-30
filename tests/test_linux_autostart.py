from astroswarm_linux import autostart


def test_unit_text_contains_required_fields(tmp_path):
    text = autostart.unit_text(tmp_path, 7860)
    assert "ExecStart=" in text and "7860" in text
    assert "Restart=on-failure" in text


def test_install_writes_unit_and_wants(tmp_path):
    unit = tmp_path / "systemd" / "system"
    wants = tmp_path / "systemd" / "multi-user.target.wants"
    autostart.install("astroswarm.service", "[Unit]", unit, wants, enable=True)
    assert (unit / "astroswarm.service").exists()
    assert (wants / "astroswarm.service").exists()
