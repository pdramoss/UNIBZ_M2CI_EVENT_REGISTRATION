from app.models.User import User


class Client(User):
    def __init__(
        self,
        id: int,
        name: str,
        password: str,
        email: str,
        age: int,
        username: str,
    ) -> None:
        super().__init__(id, name, password, email, age, username)