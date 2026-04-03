from voyager import Voyager
from api_keys import openai_api_key

# You can also use mc_port instead of azure_login, but azure_login is highly recommended
azure_login = {
    "client_id": "aaa",
    "redirect_url": "https://127.0.0.1/auth-response",
    # "secret_value": "[OPTIONAL] YOUR_SECRET_VALUE",
    "version": "fabric-loader-0.14.18-1.19", # the version Voyager is tested on
}

voyager = Voyager(
    azure_login=azure_login,
    openai_api_key=openai_api_key,
)

# start lifelong learning
voyager.learn()