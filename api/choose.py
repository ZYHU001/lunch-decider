from server import Handler


class handler(Handler):
    def do_POST(self):
        self.path = "/api/choose"
        super().do_POST()
