.PHONY: docker-cleanup docker-build docker-run

docker-cleanup:
	@echo "Stopping and removing all containers, networks, and volumes associated with this project..."
	docker compose down -v --remove-orphans
	@echo "Removing the built recipe-parser image..."
	docker rmi recipe-manager-recipe-parser-app:latest || true
	@echo "Pruning unused builder cache..."
	docker builder prune -f
	@echo "Cleanup complete."

APP_NAME := recipe-manager-app

docker-build:
	docker build -t ${APP_NAME} .

docker-run:
	docker run -it --rm ${APP_NAME}

docker-build-run: docker-build docker-run