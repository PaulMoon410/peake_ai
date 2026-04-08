class Weapon:
    def __init__(self, name, damage, ammo, fire_rate=1.0, reload_time=1.0, max_ammo=None):
        self.name = name
        self.damage = damage
        self.ammo = ammo
        self.fire_rate = fire_rate
        self.reload_time = reload_time
        self.max_ammo = max_ammo if max_ammo is not None else ammo
        self.cooldown = 0.0
        self.reloading = False
        self.reload_timer = 0.0

    def shoot(self):
        if self.reloading or self.cooldown > 0 or self.ammo <= 0:
            return False
        self.ammo -= 1
        self.cooldown = 1.0 / self.fire_rate if self.fire_rate else 0.3
        return True
