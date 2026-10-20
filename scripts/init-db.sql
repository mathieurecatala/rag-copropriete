-- Base séparée pour les tests : ils la vident librement sans toucher au corpus de démonstration.
CREATE DATABASE syndic_test;
\c syndic_test
CREATE EXTENSION IF NOT EXISTS vector;
\c syndic
CREATE EXTENSION IF NOT EXISTS vector;
