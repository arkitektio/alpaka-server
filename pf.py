import docker


api = docker.from_env()


pull = api.api.pull("hello-world", stream=False)

print(pull)
