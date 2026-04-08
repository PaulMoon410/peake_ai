
from direct.showbase.ShowBase import ShowBase
from panda3d.core import WindowProperties, DirectionalLight, AmbientLight, Vec4, Vec3
from direct.task import Task
from direct.showbase import ShowBaseGlobal
import sys
import config
from level import Level
from weapon import Weapon
from enemy import Enemy

globalClock = ShowBaseGlobal.globalClock


class FPSGameEngine(ShowBase):
    def __init__(self):
        print("Initializing FPSGameEngine...")
        super().__init__()
        print("ShowBase initialized.")
        self.set_background_color(0, 0, 0)
        print("Background color set.")

        # Hide mouse cursor and lock to window
        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)
        print("Window properties set.")

        # Modular: instantiate Level
        self.level = Level(self)
        print("Level instantiated.")

        # Modular: instantiate Player

        self.heading = 0
        self.pitch = 0
        self.mouse_sensitivity = config.MOUSE_SENSITIVITY
        self.move_speed = config.PLAYER_SPEED

        # Key state tracking
        self.key_map = {"forward": False, "back": False, "left": False, "right": False}
        self.accept("escape", sys.exit)
        self.accept("w", self.set_key, ["forward", True])
        self.accept("w-up", self.set_key, ["forward", False])
        self.accept("s", self.set_key, ["back", True])
        self.accept("s-up", self.set_key, ["back", False])
        self.accept("a", self.set_key, ["left", True])
        self.accept("a-up", self.set_key, ["left", False])
        self.accept("d", self.set_key, ["right", True])
        self.accept("d-up", self.set_key, ["right", False])

        # Mouse look
        self.taskMgr.add(self.update_camera, "UpdateCameraTask")
        print("Camera update task added.")

        # Weapon system: use Weapon objects
        self.weapons = [
            Weapon("Pistol", 18, 12, 3.5, 1.0, 12),
            Weapon("Shotgun", 8, 6, 1.1, 1.3, 6),
            Weapon("Rifle", 10, 24, 7.0, 1.5, 24),
        ]
        self.current_weapon = 0
        self.accept("mouse1", self.shoot)
        self.accept("wheel_up", self.next_weapon)
        self.accept("wheel_down", self.prev_weapon)
        print("Setting up weapons...")

        # Movement abilities
        self.accept("space", self.jump)
        self.accept("shift", self.dash)
        self.is_jumping = False
        self.is_dashing = False
        self.jump_speed = config.PLAYER_JUMP_FORCE
        self.dash_speed = self.move_speed * config.PLAYER_SPRINT_MULT
        self.gravity = config.PLAYER_GRAVITY
        self.vertical_speed = 0
        self.ground_z = config.PLAYER_SPAWN_HEIGHT
        print("Setting up movement abilities...")

        # Lighting setup
        dlight = DirectionalLight('dlight')
        dlight.setColor(Vec4(1, 1, 0.9, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(0, -60, 0)
        self.render.setLight(dlnp)
        alight = AmbientLight('alight')
        alight.setColor(Vec4(0.3, 0.3, 0.4, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)
        print("Lights added.")

        print("Spawning enemy...")
        self.enemy = Enemy(self.render, self.loader)
        print("Enemy spawned.")
        self.taskMgr.add(self.update_enemy, "UpdateEnemyTask")
        print("Enemy update task added.")

    def set_key(self, key, value):
        self.key_map[key] = value

    def jump(self):
        if not self.is_jumping:
            self.vertical_speed = self.jump_speed
            self.is_jumping = True

    def dash(self):
        if not self.is_dashing:
            self.is_dashing = True
            self.dash_timer = 0.2  # Dash lasts 0.2 seconds

    def update_camera(self, task):
        # Mouse look
        if self.mouseWatcherNode.hasMouse():
            md = self.win.getPointer(0)
            x = md.getX()
            y = md.getY()
            self.heading -= (x) * self.mouse_sensitivity
            self.pitch -= (y) * self.mouse_sensitivity
            self.pitch = max(-90, min(90, self.pitch))
            self.camera.setHpr(self.heading, self.pitch, 0)
            self.win.movePointer(0, 0, 0)

        # WASD movement
        dt = globalClock.getDt()
        direction = [0, 0, 0]
        if self.key_map["forward"]:
            direction[1] += 1
        if self.key_map["back"]:
            direction[1] -= 1
        if self.key_map["left"]:
            direction[0] -= 1
        if self.key_map["right"]:
            direction[0] += 1
        move_speed = self.move_speed
        if self.is_dashing:
            move_speed = self.dash_speed
            self.dash_timer -= dt
            if self.dash_timer <= 0:
                self.is_dashing = False
        if direction != [0, 0, 0]:
            # Move relative to camera heading
            mat = self.camera.getMat()
            move_vec = mat.xformVec(Vec3(direction[0], direction[1], 0))
            if move_vec.length() > 0:
                move_vec.normalize()
                self.camera.setPos(self.camera.getPos() + move_vec * move_speed * dt)
        # Gravity and jump
        pos = self.camera.getPos()
        if self.is_jumping:
            self.vertical_speed += self.gravity * dt
            pos.z += self.vertical_speed * dt
            if pos.z <= self.ground_z:
                pos.z = self.ground_z
                self.is_jumping = False
                self.vertical_speed = 0
            self.camera.setPos(pos)
        return Task.cont

    def shoot(self):
        weapon = self.weapons[self.current_weapon]
        if weapon.shoot():
            print(f"Fired {weapon.name}! Ammo left: {weapon.ammo}")
            # Simple hitscan: damage enemy if in front
            if self.enemy and self.enemy.alive:
                enemy_vec = self.enemy.model.getPos() - self.camera.getPos()
                enemy_vec.normalize()
                cam_vec = self.camera.getQuat().getForward()
                dot = enemy_vec.dot(cam_vec)
                if dot > 0.95:  # Enemy is in front
                    self.enemy.take_damage(weapon.damage)

    def next_weapon(self):
        self.current_weapon = (self.current_weapon + 1) % len(self.weapons)
        print(f"Switched to {self.weapons[self.current_weapon].name}")

    def prev_weapon(self):
        self.current_weapon = (self.current_weapon - 1) % len(self.weapons)
        print(f"Switched to {self.weapons[self.current_weapon].name}")

    def update_enemy(self, task):
        if self.enemy:
            self.enemy.update(self.camera.getPos(), globalClock.getDt())
        return Task.cont

if __name__ == "__main__":
    print("Starting game...")
    app = FPSGameEngine()
    print("Running app...")
    app.run()
    print("App finished.")
