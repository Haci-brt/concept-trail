"""The app was renamed; its settings must not be left behind under the old name."""
from server.providers import config_dir


def test_settings_under_the_old_name_come_along(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path))
    old = tmp_path / "FikirNotDefteri"
    old.mkdir()
    (old / "providers.json").write_text('{"roles": {}}', encoding="utf-8")

    new = config_dir()
    assert new.name == "ConceptTrail"
    assert (new / "providers.json").read_text(encoding="utf-8") == '{"roles": {}}'
    assert (old / "providers.json").exists()          # copied, not moved


def test_the_new_folder_wins_once_it_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "ConceptTrail").mkdir()
    (tmp_path / "FikirNotDefteri").mkdir()
    (tmp_path / "FikirNotDefteri" / "providers.json").write_text("eski", encoding="utf-8")
    assert not (config_dir() / "providers.json").exists()


def test_a_fresh_install_has_nothing_to_bring(tmp_path, monkeypatch):
    monkeypatch.setenv("FIKIR_CONFIG_DIR", str(tmp_path))
    assert config_dir() == tmp_path / "ConceptTrail"
    assert not (tmp_path / "ConceptTrail").exists()   # created when something is saved
