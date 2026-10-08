from server import Handler


class handler(Handler):
    def do_GET(self):
        self.path = "/api/restaurants"
        super().do_GET()
