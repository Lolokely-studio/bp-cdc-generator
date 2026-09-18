"""Couche modèles d'Esquisse.

Les cinq fournisseurs gratuits exposent tous l'API Chat Completions
d'OpenAI : un seul adaptateur suffit, seule l'URL de base change. Le point
d'entrée est `app.llm.gateway`, qui applique l'ordre des essais du §5.3 de
la spec. Rien n'est réexporté ici, pour qu'un import de paquet ne tire pas
le transport réseau quand seul le vocabulaire est nécessaire.
"""
