default:
    just --list

# code linting
lint:
    uv run black .
    uv run ruff check --fix

# crawl decks from ygo pro deck
crawl category_url="https://ygoprodeck.com/category/format/tournament%20meta%20decks" pages="100" db_path="data/ygo.sqlite":
    PYTHONPATH=src uv run python -m ygo_crawler.cli crawl-category "{{category_url}}" --pages "{{pages}}" --db-path "{{db_path}}"

# 
enrich-cards:
    PYTHONPATH=src uv run python -m ygo_crawler.cli enrich-cards --db-path "data/ygo.sqlite" --batch-size "40"

# import a card databse from ygo pro deck
dump-csv:
    PYTHONPATH=src uv run python -m ygo_crawler.cli export-cards-csv --db-path "data/ygo.sqlite" --output "exports/deck_cards_flat.csv"

# run streamlit dashboard
dashboard db_path="data/ygo.sqlite":
    PYTHONPATH=src uv run streamlit run dashboard/app.py -- --db-path "{{db_path}}"

export-dependencys:
    uv pip freeze > requirements.txt 