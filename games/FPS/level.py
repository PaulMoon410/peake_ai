# level.py
from panda3d.core import NodePath, Vec3
import config

class Level:
    def __init__(self, game):
        self.game = game
        self.node = NodePath("level")
        self.node.reparentTo(game.render)
        self.build_arena()

    def build_arena(self):
        # Floor
        floor = self.game.loader.loadModel("models/box")
        floor.reparentTo(self.node)
        floor.setScale(config.LEVEL_SIZE, config.LEVEL_SIZE, 0.2)
        floor.setPos(0, 0, 0)
        floor.setColor(0.25, 0.25, 0.28, 1)
        # Walls
        for i in range(4):
            wall = self.game.loader.loadModel("models/box")
            wall.reparentTo(self.node)
            if i < 2:
                wall.setScale(config.LEVEL_SIZE, 0.5, 3)
                wall.setPos(0, (-1)**i * config.LEVEL_SIZE/2, 1.5)
            else:
                wall.setScale(0.5, config.LEVEL_SIZE, 3)
                wall.setPos((-1)**i * config.LEVEL_SIZE/2, 0, 1.5)
            wall.setColor(0.18, 0.19, 0.22, 1)
        # Obstacles
        for i in range(5):
            obs = self.game.loader.loadModel("models/box")
            obs.reparentTo(self.node)
            obs.setScale(1.2, 1.2, 2.5)
            obs.setPos((i-2)*5, (i%2)*8-4, 1.25)
            obs.setColor(0.3, 0.3, 0.35, 1)
