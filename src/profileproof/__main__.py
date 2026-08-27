import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "profileproof.app:app",
        host="0.0.0.0",  # noqa: S104 - required inside the container
        port=int(os.getenv("PORT", "8080")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
