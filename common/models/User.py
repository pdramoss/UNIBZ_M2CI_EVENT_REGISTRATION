class User:
    id: int
    name: str
    password: str
    email: str
    age: int
    username: str

    def __init__(
        self,
        id: int,
        name: str,
        password: str,
        email: str,
        age: int,
        username: str,
    ) -> None:
        self.id = id
        self.name = name
        self.password = password
        self.email = email
        self.age = age
        self.username = username

    def get_id(self) -> int:
        return self.id

    def set_id(self, id: int) -> None:
        self.id = id

    def get_name(self) -> str:
        return self.name

    def set_name(self, name: str) -> None:
        self.name = name

    def get_password(self) -> str:
        return self.password

    def set_password(self, password: str) -> None:
        self.password = password

    def get_email(self) -> str:
        return self.email

    def set_email(self, email: str) -> None:
        self.email = email

    def get_age(self) -> int:
        return self.age

    def set_age(self, age: int) -> None:
        self.age = age

    def get_username(self) -> str:
        return self.username

    def set_username(self, username: str) -> None:
        self.username = username