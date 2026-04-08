class Player:
    def __init__(self, camera):
        self.camera = camera
        self.health = 100
        self.ammo = 100
        self.position = camera.getPos()
        self.velocity = [0, 0, 0]
        self.is_jumping = False
        self.is_dashing = False
        self.jump_speed = 12
        self.dash_speed = 30
        self.gravity = -30
        self.vertical_speed = 0
        self.ground_z = 2

    def update(self):
        self.position = self.camera.getPos()
        # Add more player logic here
