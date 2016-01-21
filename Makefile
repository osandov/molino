.PHONY: all

all:

.PHONY: test
test:
	python3 -m unittest discover tests/

.PHONY: coverage
coverage:
	coverage3 run --source=molino/ -m unittest discover tests/ || true
	coverage3 report
	coverage3 html
