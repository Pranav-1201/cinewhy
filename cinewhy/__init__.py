"""CineWhy — a movie recommender that explains itself with review evidence.

Module map (ARCHITECTURE.md §5). Each module owns one concern and may not reach
across the boundary into another:

    schemas    the contract every other module speaks — change by agreement only
    text       normalisation, shared by training and serving
    absa       aspect detection and polarity
    data       ingestion and joins            (Phase D)
    recsys     collaborative filtering and ranking  (Phase D)
    artifacts  build, hash and verify what the API loads at boot
"""

__version__ = "0.1.0"
