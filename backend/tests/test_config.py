from app.core.config import Settings


def test_env_var_overrides_env_file(tmp_path, monkeypatch):
    """Le `.env` de la racine du dépôt peut contenir des identifiants Supabase
    de production ; une variable d'environnement déjà posée doit toujours
    l'emporter dessus (c'est le rôle de l'affectation ferme de conftest.py
    pour les tests). La preuve ne doit pas dépendre du contenu du vrai `.env`
    racine : il est ignoré par git, donc absent sur un clone neuf ou en
    intégration continue — un test qui s'appuierait dessus passerait au vert
    en ne testant rien dans ce cas. On construit donc ici un `.env` temporaire
    autonome, avec une valeur connue, et on le passe explicitement via
    `_env_file` (qui l'emporte sur le `env_file` du `model_config`)."""
    env_file = tmp_path / ".env"
    env_file.write_text("SUPABASE_DB_NAME=valeur_du_fichier\n")

    # Sans variable d'environnement : la valeur vient bien du fichier temporaire
    # (sinon on ne saurait pas si celui-ci a seulement été pris en compte).
    monkeypatch.delenv("SUPABASE_DB_NAME", raising=False)
    settings_without_env = Settings(_env_file=env_file)
    assert settings_without_env.supabase_db_name == "valeur_du_fichier"

    # Avec une variable d'environnement conflictuelle : elle l'emporte sur le fichier.
    monkeypatch.setenv("SUPABASE_DB_NAME", "valeur_de_environnement")
    settings_with_env = Settings(_env_file=env_file)
    assert settings_with_env.supabase_db_name == "valeur_de_environnement"


def test_fake_llm_reads_esquisse_fake_llm_env_var(monkeypatch):
    """`fake_llm` est lié par alias à la variable `ESQUISSE_FAKE_LLM`
    (documentée au §11 de la spec), pas au nom `FAKE_LLM` que
    pydantic-settings aurait dérivé par défaut du nom du champ. Ce câblage
    n'est pas visible à la seule lecture du type ; ce test le fixe pour
    qu'un futur renommage ne le casse pas en silence."""
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    assert Settings().fake_llm is True
