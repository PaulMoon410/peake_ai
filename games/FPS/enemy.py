from panda3d.core import Vec3

class Enemy:
    def __init__(self, render, loader, pos=(5, 10, 2)):
        self.model = loader.loadModel("models/box")
        self.model.setColor(1, 0, 0, 1)
        self.model.setScale(1, 1, 1)
        self.model.setPos(*pos)
        self.model.reparentTo(render)
        import config
        self.health = config.ENEMY_HEALTH
        self.alive = True

    def take_damage(self, amount):
        if self.alive:
            self.health -= amount
            print(f"Enemy health: {self.health}")
            if self.health <= 0:
                self.die()

    def die(self):
        self.alive = False
        self.model.removeNode()
        print("Enemy defeated!")

    def update(self, player_pos, dt):
        if not self.alive:
            return
        direction = player_pos - self.model.getPos()
        direction.z = 0
        if direction.length() > 0.1:
            direction.normalize()
            import config
            self.model.setPos(self.model.getPos() + direction * config.ENEMY_SPEED * dt)
