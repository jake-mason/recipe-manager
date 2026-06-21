.PHONY: docker-cleanup docker-build docker-run test

test:
	python3 -m pytest tests/ -v

docker-cleanup:
	docker compose down --volumes --remove-orphans --rmi all
	docker system prune -a --volumes --force

APP_NAME := recipe-manager-app

dc-build:
	docker compose build

dc-down:
	docker compose down

dc-up:
	docker compose up

docker-build:
	docker build -t ${APP_NAME} .

docker-run:
	docker run -it --rm ${APP_NAME}

docker-build-run: docker-build docker-run