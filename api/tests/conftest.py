import os

# Affectation ferme (et non `setdefault`) : le `.env` à la racine du dépôt
# contient les identifiants de la base Supabase de production, et un
# développeur peut avoir ces variables SUPABASE_DB_* déjà exportées dans son
# shell. Avec `setdefault`, ces valeurs existantes passeraient au travers et
# la suite de tests s'exécuterait alors contre la base réelle. L'affectation
# ferme écrase toute valeur préexistante et garantit que les tests ne parlent
# jamais qu'à la base jetable de docker-compose.
os.environ["SUPABASE_DB_HOST"] = "localhost"
os.environ["SUPABASE_DB_PORT"] = "5433"
os.environ["SUPABASE_DB_USER"] = "esquisse"
os.environ["SUPABASE_DB_PASSWORD"] = "esquisse"
os.environ["SUPABASE_DB_NAME"] = "esquisse_test"
