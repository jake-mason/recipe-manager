.PHONY: docker-cleanup docker-build docker-run

docker-cleanup:
	docker system prune -a --volumes --force
	docker rm -f $(docker ps -aq)
	docker rmi -f $(docker images -q)

APP_NAME := recipe-manager-app

docker-build:
	docker build -t ${APP_NAME} .

docker-run:
	docker run -it --rm ${APP_NAME}

docker-build-run: docker-build docker-run