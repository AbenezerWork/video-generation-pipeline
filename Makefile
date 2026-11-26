FILM_PROJECTS ?= examples/lions-whisker-16x9 examples/lions-whisker-9x16

.PHONY: setup test film

setup:
	uv sync --locked --all-extras

test:
	uv run --locked ruff check src tests
	uv run --locked ruff format --check src tests
	uv run --locked pyright
	uv run --locked pytest -q

film:
	@set -e; for project in $(if $(PROJECT),$(PROJECT),$(FILM_PROJECTS)); do \
		uv run vidpipe run "$$project" --auto; \
	done
