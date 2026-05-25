.PHONY: docker-cleanup

docker-cleanup:
	@echo "Stopping and removing all containers, networks, and volumes associated with this project..."
	docker compose down -v --remove-orphans
	@echo "Removing the built recipe-parser image..."
	docker rmi recipe-manager-recipe-parser-app:latest || true
	@echo "Pruning unused builder cache..."
	docker builder prune -f
	@echo "Cleanup complete."
