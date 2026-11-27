#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHOTGUN KING — мини-рогалик в стиле Shotgun King.

Ты — Король на шахматном поле 8x8. На тебя волнами наступают враги,
ходящие по шахматным правилам (пешки, ладьи, кони). Ты ходишь на 1 клетку
в любом направлении; ход на клетку с врагом = АТАКА дробовиком:
враг получает урон и ОТБРАСЫВАЕТСЯ назад (как отдачей от выстрела).

За убийства даются монеты — между волнами можно покупать улучшения
(новое оружие, патроны, HP) как карта-дроп у оригинала.

Управление:
  WASD / стрелки + Q/E/Z/C  — ход и атака (как ход короля в шахматах)
  ПРОБЕЛ                    — «выстрел на месте»: удар по всем соседям (тратит PATRONY)
  R                         — заново после смерти
  ENTER                     — купить улучшение (между волнами) / пропустить волну
Зависимости: pygame  (pip install pygame)
"""

import math
import random
import sys

import pygame

# ----------------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------------
CELL        = 72                 # пиксельный размер клетки
BOARD       = 8                  # поле 8x8
ORIGIN      = (60, 90)           # левый верхний угол поля на экране
HUD_X       = ORIGIN[0] + BOARD * CELL + 40
WIN_W       = HUD_X + 320
WIN_H       = max(ORIGIN[1] + BOARD * CELL + 40, 640)
FPS         = 60

MOVE_CD     = 0.14               # минимальный интервал между ходами игрока (сек)
TURN_MS     = 620                # период такта врагов (мс)
KNOCK_SPEED = 14.0               # скорость анимации отбрасывания (клеток/сек)

C_BG      = (26, 24, 30)
C_DARK    = (58, 66, 58)
C_LIGHT   = (122, 130, 112)
C_BORDER  = (210, 205, 190)
C_TEXT    = (235, 235, 225)
C_GOLD    = (240, 200, 60)
C_RED     = (220, 60, 60)
C_GREEN   = (90, 200, 110)
C_DIM     = (150, 150, 150)

# ----------------------------------------------------------------------------
# Оружие (как дроп-карты в Shotgun King)
# WEAK  — только ортогональные соседи
# MED   — все 8 соседей
# HEAVY — всё сразу + пробивает насквозь (бьёт и вторую клетку по направлению)
# ---------------------------------------------------------------------------
WEAPONS = [
    {"name": "КУЛАКИ",            "dmg": 1, "orth_only": True,  "pierce": False, "price": 0},
    {"name": "ОБРЕЗ",             "dmg": 2, "orth_only": True,  "pierce": False, "price": 10},
    {"name": "ДРОБОВИК",          "dmg": 2, "orth_only": False, "pierce": False, "price": 20},
    {"name": "БОЙНАЯ ЛЮБИТЕЛЬСКАЯ", "dmg": 3, "orth_only": False, "pierce": True, "price": 35},
    {"name": "МАГНУМ .44",        "dmg": 4, "orth_only": False, "pierce": True,  "price": 55},
]

UPGRADES = [
    ("hp",     "МАМИНО МОЛОКО   +6 HP"),
    ("ammo",   "ПАТРОНЫ x3      4 монеты"),
    ("regen",  "ЛЕКАРСТВО       -1 монета за рану? Нет: лечит 3 HP за 6 монет"),
    ("weapon", "НОВОЕ ОРУЖИЕ    следующая пушка из списка"),
]


def cell_rect(c):
    """Экранный прямоугольник клетки (c — колодка (x, y) в клетках, float ok)."""
    return pygame.Rect(ORIGIN[0] + c[0] * CELL, ORIGIN[1] + c[1] * CELL, CELL, CELL)


# ----------------------------------------------------------------------------
# Сущности
# ----------------------------------------------------------------------------
class Enemy:
    def __init__(self, kind, pos, side, wave):
        self.kind = kind                 # 'P' пешка, 'R' ладья, 'N' конь
        self.pos = [pos[0], pos[1]]      # логическая клетка
        self.side = side                 # сторона появления (для направления «вперёд»)
        self.alive = True
        self.flash = 0.0                 # таймер вспышки при получении урона
        # характеристики растут с волной
        if kind == "P":
            self.hp = self.max_hp = 2 + wave // 2
            self.dmg = 1
            self.reward = 2
        elif kind == "R":
            self.hp = self.max_hp = 3 + wave
            self.dmg = 2
            self.reward = 5
        else:  # 'N'
            self.hp = self.max_hp = 2 + wave // 2
            self.dmg = 2
            self.reward = 4
        # визуальная позиция (float) — может отличаться при knockback-анимации
        self.vpos = [float(pos[0]), float(pos[1])]
        self.knock = None                # [(x,y), ...] путь отбрасывания для анимации

    # направление «вперёд» (к центру) для данной стороны
    @staticmethod
    def fwd(side):
        return {"T": (0, 1), "B": (0, -1), "L": (1, 0), "R": (-1, 0)}[side]

    def start_knockback(self, cells):
        """Запускаем анимацию отлёта: cells — список клеток по порядку."""
        self.knock = [tuple(c) for c in cells]


class Particle:
    """Дым/дух от выстрела."""
    def __init__(self, x, y, vx, vy, life, color, size):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = self.max_life = life
        self.color = color
        self.size = size

    def update(self, dt):
        self.life -= dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 40 * dt  # лёгкая гравитация дыма
        return self.life > 0


class FloatText:
    def __init__(self, x, y, text, color):
        self.x, self.y, self.text, self.color = x, y, text, color
        self.life = 1.0

    def update(self, dt):
        self.life -= dt
        self.y -= 28 * dt
        return self.life > 0


# ----------------------------------------------------------------------------
# Игра
# ----------------------------------------------------------------------------
class Game:
    def __init__(self, screen):
        self.screen = screen
        self.font_big = pygame.font.SysFont("dejavusans,arial", 26, bold=True)
        self.font = pygame.font.SysFont("dejavusans,arial", 18)
        self.font_small = pygame.font.SysFont("dejavusans,arial", 14)
        self.reset()

    def reset(self):
        cx = BOARD // 2
        self.king = {"pos": [cx, cx], "hp": 12, "max_hp": 12,
                     "vpos": [float(cx), float(cx)], "move_cd": 0.0}
        self.enemies = []
        self.particles = []
        self.floats = []
        self.shake = 0.0
        self.wave = 1
        self.kills = 0
        self.coins = 0
        self.ammo = 0                      # «выстрел на месте» стоит 1 патрон
        self.weapon_idx = 0
        self.turn_timer = 0
        self.game_over = False
        self.intermission = 0.0            # пауза между волнами (сек)
        self.message = "ВОЛНА 1: они идут со всех сторон!"
        self.msg_timer = 3.0
        self.spawn_wave()

    # ------------------------------------------------------------------ спавн
    def spawn_wave(self):
        sides = ["T", "B", "L", "R"]
        n = min(3 + self.wave, 10)
        chosen = random.sample(sides, k=min(2 + self.wave // 3, 4))
        kinds = ["P"] * 6
        if self.wave >= 2:
            kinds += ["N"] * 2
        if self.wave >= 3:
            kinds += ["R"] * 2
        for _ in range(n):
            side = random.choice(chosen)
            off = 1
            if side == "T":
                pos = (random.randrange(BOARD), -off)
            elif side == "B":
                pos = (random.randrange(BOARD), BOARD - 1 + off)
            elif side == "L":
                pos = (-off, random.randrange(BOARD))
            else:
                pos = (BOARD - 1 + off, random.randrange(BOARD))
            e = Enemy(random.choice(kinds), pos, side, self.wave)
            # не спавним двух врагов в одной клетке
            if any(en.alive and en.pos == list(e.pos) for en in self.enemies):
                continue
            self.enemies.append(e)

    # ------------------------------------------------------------- эффекты
    def boom(self, cell, color=(250, 230, 150)):
        cx = ORIGIN[0] + (cell[0] + 0.5) * CELL
        cy = ORIGIN[1] + (cell[1] + 0.5) * CELL
        for _ in range(14):
            a = random.uniform(0, math.tau)
            s = random.uniform(60, 260)
            self.particles.append(Particle(cx, cy, math.cos(a) * s, math.sin(a) * s,
                                           random.uniform(0.25, 0.6), color,
                                           random.randint(3, 7)))
        self.shake = min(self.shake + 0.35, 0.9)

    def say(self, text, t=2.2):
        self.message = text
        self.msg_timer = t

    # ------------------------------------------------------------ стрельба
    def weapon(self):
        return WEAPONS[self.weapon_idx]

    def shoot_dir(self, dx, dy):
        """Выстрел в направлении (dx,dy) ∈ {-1,0,1}. Возвращает True если попал."""
        w = self.weapon()
        if w["orth_only"] and dx != 0 and dy != 0:
            return False
        hit_any = False
        rng = 2 if w["pierce"] else 1
        kx, ky = self.king["pos"]
        for step in range(1, rng + 1):
            tx, ty = kx + dx * step, ky + dy * step
            if not (0 <= tx < BOARD and 0 <= ty < BOARD):
                break
            foe = self.enemy_at((tx, ty))
            if foe:
                self.damage(foe, w["dmg"], kb_steps=3 if step == 1 else 2)
                hit_any = True
        return hit_any

    def blast_around(self):
        """Пробел: удар по всем соседям (тратит 1 патрон)."""
        if self.ammo <= 0:
            self.say("Нет патронов! Купи их в лавке (клавиша 2).")
            return
        self.ammo -= 1
        w = self.weapon()
        hit = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                if w["orth_only"] and dx != 0 and dy != 0:
                    continue
                tx, ty = self.king["pos"][0] + dx, self.king["pos"][1] + dy
                foe = self.enemy_at((tx, ty))
                if foe:
                    self.damage(foe, w["dmg"])
                    hit += 1
        self.boom(self.king["pos"], (255, 160, 80))
        if hit == 0:
            self.say("Пустой выстрел... дым из дула.")

    def damage(self, foe, dmg, kb_steps=3):
        """Урон + отбрасывание по направлению выстрела (от короля)."""
        foe.hp -= dmg
        foe.flash = 0.25
        kx, ky = self.king["pos"]
        dx = sign(foe.pos[0] - kx)
        dy = sign(foe.pos[1] - ky)
        if dx == 0 and dy == 0:
            dx, dy = 0, -1
        path = []
        cx, cy = foe.pos
        for _ in range(kb_steps):
            nx, ny = cx + dx, cy + dy
            # упёрся во что-то — останавливаемся перед препятствием
            if blocked_for_enemy(nx, ny, foe, self.enemies):
                break
            path.append((nx, ny))
            cx, cy = nx, ny
        if path:
            foe.pos = list(path[-1])
            foe.start_knockback(path)
        if foe.hp <= 0:
            foe.alive = False
            self.kills += 1
            self.coins += foe.reward
            self.boom(foe.pos, (200, 200, 210))
            self.floats.append(FloatText(cell_center_px(foe.pos)[0],
                                         cell_center_px(foe.pos)[1],
                                         f"+{foereward_str(foe)}", C_GOLD))
        else:
            self.floats.append(FloatText(cell_center_px(foe.pos)[0],
                                         cell_center_px(foe.pos)[1],
                                         f"-{dmg}", C_RED))

    # ------------------------------------------------------------ движение
    def try_move(self, dx, dy):
        if self.game_over or self.king["move_cd"] > 0:
            return
        self.king["move_cd"] = MOVE_CD
        tx, ty = self.king["pos"][0] + dx, self.king["pos"][1] + dy
        if not (0 <= tx < BOARD and 0 <= ty < BOARD):
            return
        foe = self.enemy_at((tx, ty))
        if foe:
            self.shoot_dir(dx, dy)
            self.boom(self.king["pos"])
        else:
            self.king["pos"] = [tx, ty]

    def enemy_at(self, cell):
        for e in self.enemies:
            if e.alive and e.pos[0] == cell[0] and e.pos[1] == cell[1]:
                return e
        return None

    # ---------------------------------------------------------- ИИ врагов
    def enemy_turn(self):
        kp = tuple(self.king["pos"])
        for e in self.enemies:
            if not e.alive or e.knock:
                continue
            fx, fy = e.fwd(e.side)
            rx, ry = fy, -fx  # перпендикуляр

            if e.kind == "P":
                # атака по диагоналям вперёд
                for d in ((fx + rx, fy + ry), (fx - rx, fy - ry)):
                    if (e.pos[0] + d[0], e.pos[1] + d[1]) == kp:
                        self.hit_king(e, e.dmg)
                        break
                else:
                    one = (e.pos[0] + fx, e.pos[1] + fy)
                    two = (e.pos[0] + 2 * fx, e.pos[1] + 2 * fy)
                    if one == kp:
                        pass  # встал вплотную к королю — рубит в следующий такт
                    elif getattr(e, "first", True) and inside_board(two) \
                            and not self.cell_busy(two, e) and not self.cell_busy(one, e) \
                            and one != kp:
                        e.pos = list(two)
                        e.first = False
                    elif inside_board_or_off(one) and not self.cell_busy(one, e):
                        e.pos = list(one)
                        e.first = False
            elif e.kind == "R":
                # ладья: едет по своей оси к линии короля, бьёт по прямой
                horiz = e.side in ("L", "R")
                axis_delta = (kp[0] - e.pos[0]) if horiz else (kp[1] - e.pos[1])
                cross_ok = (kp[1] == e.pos[1]) if horiz else (kp[0] == e.pos[0])
                if cross_ok and axis_delta != 0 and abs(axis_delta) <= BOARD + 2:
                    self.hit_king(e, e.dmg)
                else:
                    step = sign(axis_delta)
                    nxt = (e.pos[0] + (step if horiz else 0),
                           e.pos[1] + (0 if horiz else step))
                    if not self.cell_busy(nxt, e) and nxt != kp:
                        e.pos = list(nxt)
            else:  # 'N' конь
                jumps = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)]
                targets = [(e.pos[0] + j[0], e.pos[1] + j[1]) for j in jumps]
                if kp in targets:
                    self.hit_king(e, e.dmg)
                else:
                    cand = [t for t in targets if inside_board(t) and not self.cell_busy(t, e)]
                    if cand:
                        cand.sort(key=lambda t: manhattan(t, kp))
                        if random.random() < 0.85:
                            e.pos = list(cand[0])
            # прошёл за противоположный край — уходит
            if not (-2 <= e.pos[0] <= BOARD + 1 and -2 <= e.pos[1] <= BOARD + 1):
                e.alive = False

    def hit_king(self, e, dmg):
        self.king["hp"] -= dmg
        self.shake = min(self.shake + 0.5, 1.0)
        kc = cell_center_px(self.king["pos"])
        self.floats.append(FloatText(kc[0], kc[1], f"-{dmg}", C_RED))
        if self.king["hp"] <= 0:
            self.game_over = True
            self.say(f"GAME OVER. Волн: {self.wave}, убийств: {self.kills}. R — заново.", 999)

    def cell_busy(self, cell, ignore):
        if not inside_board(cell):
            return True
        for e in self.enemies:
            if e is not ignore and e.alive and e.pos[0] == cell[0] and e.pos[1] == cell[1]:
                return True
        return False

    # --------------------------------------------------------- покупки
    def buy(self, idx):
        if self.intermission <= 0 or self.game_over:
            return
        if idx == 0:  # HP
            price = 6
            if self.coins < price:
                self.say("Не хватает монет!")
                return
            if self.king["hp"] >= self.king["max_hp"]:
                self.say("Здоровье полное!")
                return
            self.coins -= price
            self.king["hp"] = min(self.king["max_hp"], self.king["hp"] + 6)
            self.say("Выпито маммино молоко. +6 HP")
        elif idx == 1:  # патроны
            price = 4
            if self.coins < price:
                self.say("Не хватает монет!")
                return
            self.coins -= price
            self.ammo += 3
            self.say("Куплено 3 патрона. ПРОБЕЛ — залп вокруг!")
        elif idx == 2:  # оружие
            if self.weapon_idx >= len(WEAPONS) - 1:
                self.say("Лучшее оружие уже в руках!")
                return
            price = WEAPONS[self.weapon_idx + 1]["price"]
            if self.coins < price:
                self.say("Не хватает монет!")
                return
            self.coins -= price
            self.weapon_idx += 1
            self.say(f"Новое оружие: {self.weapon()['name']}!")

    # -------------------------------------------------------------- цикл
    def update(self, dt):
        # таймеры
        self.king["move_cd"] = max(0.0, self.king["move_cd"] - dt)
        self.shake = max(0.0, self.shake - dt * 2.2)
        self.msg_timer = max(0.0, self.msg_timer - dt)
        for e in self.enemies:
            e.flash = max(0.0, e.flash - dt)
        self.particles = [p for p in self.particles if p.update(dt)]
        self.floats = [f for f in self.floats if f.update(dt)]

        # анимация отбрасывания: vpos летит по точкам knock-пути
        for e in self.enemies:
            if e.knock:
                speed = KNOCK_SPEED * dt
                while speed > 0 and e.knock:
                    tgt = e.knock[0]
                    dx, dy = tgt[0] - e.vpos[0], tgt[1] - e.vpos[1]
                    dist = math.hypot(dx, dy)
                    if dist <= speed:
                        e.vpos = [float(tgt[0]), float(tgt[1])]
                        speed -= dist
                        e.knock.pop(0)
                    else:
                        e.vpos = [e.vpos[0] + dx / dist * speed,
                                  e.vpos[1] + dy / dist * speed]
                        speed = 0
            else:
                # обычное следование vpos за pos (плавно)
                for i in range(2):
                    d = e.pos[i] - e.vpos[i]
                    if abs(d) > 0.001:
                        e.vpos[i] += d * min(1.0, 12 * dt)

        kd = [self.king["pos"][0] - self.king["vpos"][0],
              self.king["pos"][1] - self.king["vpos"][1]]
        for i in range(2):
            if abs(kd[i]) > 0.001:
                self.king["vpos"][i] += kd[i] * min(1.0, 18 * dt)

        if self.game_over:
            return

        # межволновая пауза
        if self.intermission > 0:
            self.intermission -= dt
            if self.intermission <= 0:
                self.wave += 1
                self.spawn_wave()
                self.say(f"ВОЛНА {self.wave}!")
            return

        # конец волны?
        if not any(e.alive for e in self.enemies):
            self.intermission = 999.0  # ждём решения игрока (Enter)
            self.say("Волна отбита! Лавка открыта. ENTER — следующая волна.")
            return

        # такт врагов
        self.turn_timer += dt * 1000
        if self.turn_timer >= TURN_MS:
            self.turn_timer = 0
            self.enemy_turn()

    # ------------------------------------------------------------- ввод
    def on_key(self, key):
        if self.game_over:
            if key == pygame.K_r:
                self.reset()
            return
        m = {
            pygame.K_w: (0, -1), pygame.K_UP: (0, -1),
            pygame.K_s: (0, 1),  pygame.K_DOWN: (0, 1),
            pygame.K_a: (-1, 0), pygame.K_LEFT: (-1, 0),
            pygame.K_d: (1, 0),  pygame.K_RIGHT: (1, 0),
            pygame.K_q: (-1, -1), pygame.K_e: (1, -1),
            pygame.K_z: (-1, 1),  pygame.K_c: (1, 1),
        }
        if key in m:
            self.try_move(*m[key])
        elif key == pygame.K_SPACE:
            self.blast_around()
        elif key == pygame.K_RETURN and self.intermission > 0:
            self.intermission = 0
            self.wave += 1
            self.spawn_wave()
            self.say(f"ВОЛНА {self.wave}!")
        elif key == pygame.K_1:
            self.buy(0)
        elif key == pygame.K_2:
            self.buy(1)
        elif key == pygame.K_3:
            self.buy(2)
        elif key == pygame.K_r:
            self.reset()

    # ---------------------------------------------------------- отрисовка
    def draw(self):
        s = self.screen
        s.fill(C_BG)
        ox = oy = 0
        if self.shake > 0:
            ox = random.uniform(-1, 1) * self.shake * 8
            oy = random.uniform(-1, 1) * self.shake * 8

        # доска
        board_px = pygame.Rect(ORIGIN[0] + ox, ORIGIN[1] + oy, BOARD * CELL, BOARD * CELL)
        pygame.draw.rect(s, C_BORDER, board_px.inflate(8, 8))
        for y in range(BOARD):
            for x in range(BOARD):
                r = cell_rect((x, y)).move(ox, oy)
                pygame.draw.rect(s, C_DARK if (x + y) % 2 == 0 else C_LIGHT, r)

        # подсветка клеток атаки
        w = self.weapon()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                if w["orth_only"] and dx != 0 and dy != 0:
                    continue
                tx, ty = self.king["pos"][0] + dx, self.king["pos"][1] + dy
                if 0 <= tx < BOARD and 0 <= ty < BOARD:
                    r = cell_rect((tx, ty)).move(ox, oy)
                    ov = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                    ov.fill((255, 80, 40, 36))
                    s.blit(ov, r.topleft)

        # враги (clip по доске, чтобы красиво въезжали из-за края)
        clip = s.get_clip()
        s.set_clip(board_px)
        for e in self.enemies:
            if e.alive:
                self.draw_enemy(s, e, ox, oy)
        self.draw_king(s, ox, oy)
        s.set_clip(clip)

        # частицы поверх
        for p in self.particles:
            a = max(0, min(255, int(255 * p.life / p.max_life)))
            r = max(1, int(p.size * p.life / p.max_life))
            surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(surf, (*p.color, a), (r, r), r)
            s.blit(surf, (p.x + ox - r, p.y + oy - r))
        for f in self.floats:
            img = self.font_small.render(f.text, True, f.color)
            img.set_alpha(int(255 * min(1.0, f.life)))
            s.blit(img, (f.x + ox - img.get_width() // 2, f.y + oy))

        self.draw_hud()

        # сообщение
        if self.msg_timer > 0:
            img = self.font.render(self.message, True, C_GOLD)
            s.blit(img, (ORIGIN[0], ORIGIN[1] - 34))

        if self.intermission > 0 and not self.game_over:
            self.draw_shop()

        if self.game_over:
            ov = pygame.Surface((BOARD * CELL, BOARD * CELL), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 180))
            s.blit(ov, board_px.topleft)
            t1 = self.font_big.render("GAME OVER", True, C_RED)
            t2 = self.font.render(f"Волн: {self.wave}  Убийств: {self.kills}  R — заново",
                                  True, C_TEXT)
            s.blit(t1, t1.get_rect(center=board_px.center).move(0, -30))
            s.blit(t2, t2.get_rect(center=board_px.center).move(0, 10))

    def draw_king(self, s, ox, oy):
        r = cell_rect(tuple(self.king["vpos"])).move(ox, oy)
        pygame.draw.circle(s, C_GOLD, r.center, CELL // 2 - 10)
        pygame.draw.circle(s, (120, 90, 10), r.center, CELL // 2 - 10, 3)
        # корона
        cx, cy = r.center
        pts = [(cx - 14, cy + 2), (cx - 14, cy - 12), (cx - 7, cy - 4),
               (cx, cy - 16), (cx + 7, cy - 4), (cx + 14, cy - 12), (cx + 14, cy + 2)]
        pygame.draw.polygon(s, (90, 60, 5), pts)
        pygame.draw.polygon(s, C_GOLD, pts, 0)
        img = self.font.render("♚", True, (60, 45, 0))
        s.blit(img, img.get_rect(center=(cx, cy + 14)))

    def draw_enemy(self, s, e, ox, oy):
        r = cell_rect(tuple(e.vpos)).move(ox, oy)
        base = {"P": (70, 70, 80), "R": (120, 60, 60), "N": (70, 100, 140)}[e.kind]
        col = (255, 255, 255) if e.flash > 0 else base
        pygame.draw.circle(s, col, r.center, CELL // 2 - 14)
        pygame.draw.circle(s, (10, 10, 14), r.center, CELL // 2 - 14, 3)
        sym = {"P": "♟", "R": "♜", "N": "♞"}[e.kind]
        img = self.font.render(sym, True, (240, 240, 240))
        s.blit(img, img.get_rect(center=r.center))
        # hp-бар
        bw = CELL - 22
        frac = max(0.0, e.hp / e.max_hp)
        bar = pygame.Rect(r.x + 11, r.bottom - 12, bw, 5)
        pygame.draw.rect(s, (70, 20, 20), bar)
        pygame.draw.rect(s, C_RED, bar.inflate(-int(bw * (1 - frac)), 0))

    def draw_hud(self):
        s = self.screen
        x = HUD_X
        y = ORIGIN[1]
        s.blit(self.font_big.render("SHOTGUN KING", True, C_GOLD), (x, y - 46))
        lines = [
            (f"Волна: {self.wave}    Убийств: {self.kills}", C_TEXT),
            (f"Монеты: {self.coins}", C_GOLD),
            (f"Оружие: {self.weapon()['name']}  (урон {self.weapon()['dmg']}"
             + (", сквозь" if self.weapon()['pierce'] else "") + ")", C_TEXT),
            (f"Патроны (ПРОБЕЛ — залп вокруг): {self.ammo}", C_TEXT),
        ]
        for txt, col in lines:
            s.blit(self.font.render(txt, True, col), (x, y)); y += 26
        y += 8
        # HP бар
        s.blit(self.font.render("Здоровье:", True, C_TEXT), (x, y)); y += 22
        bar = pygame.Rect(x, y, 240, 20)
        pygame.draw.rect(s, (70, 20, 20), bar)
        frac = max(0.0, self.king["hp"] / self.king["max_hp"])
        pygame.draw.rect(s, C_GREEN, bar.inflate(-int(240 * (1 - frac)), 0))
        s.blit(self.font.render(f"{max(0,self.king['hp'])} / {self.king['max_hp']}", True, (20, 20, 20)),
               (bar.centerx - 28, y + 1))
        y += 36
        help_lines = [
            "WASD / стрелки — ход короля,",
            "Q E Z C — диагонали.",
            "Ход на врага = ВЫСТРЕЛ:",
            "урон + отдача (враг отлетает).",
            "ПРОБЕЛ — залп по соседям (патрон).",
            "",
            "Лавка между волнами:",
            "1 — молоко (+6 HP, 6 монет)",
            "2 — патроны x3 (4 монеты)",
            "3 — новое оружие (цена растёт)",
            "ENTER — следующая волна.  R — заново.",
        ]
        for hl in help_lines:
            s.blit(self.font_small.render(hl, True, C_DIM), (x, y)); y += 20

    def draw_shop(self):
        s = self.screen
        bx = ORIGIN[0]
        by = ORIGIN[1] + BOARD * CELL // 2 - 110
        wdt = BOARD * CELL
        panel = pygame.Rect(bx, by, wdt, 220)
        ov = pygame.Surface((wdt, 220), pygame.SRCALPHA)
        ov.fill((15, 15, 20, 225))
        s.blit(ov, panel.topleft)
        pygame.draw.rect(s, C_GOLD, panel, 2)
        title = self.font_big.render("ЛАВКА ДРОППА", True, C_GOLD)
        s.blit(title, title.get_rect(midtop=(panel.centerx, by + 12)))
        items = [
            "[1] МАМИНО МОЛОКО   +6 HP        — 6 монет",
            "[2] ПАТРОНЫ x3                   — 4 монеты",
        ]
        if self.weapon_idx + 1 < len(WEAPONS):
            nw = WEAPONS[self.weapon_idx + 1]
            items.append(f"[3] ОРУЖИЕ: {nw['name']} (урон {nw['dmg']}) — {nw['price']} монет")
        else:
            items.append("[3] Лучше оружия нет.")
        yy = by + 60
        for it in items:
            if isinstance(it, str):
                s.blit(self.font.render(it, True, C_TEXT), (bx + 30, yy))
                yy += 32
        hint = self.font.render(f"Твои монеты: {self.coins}   ENTER — в бой!", True, C_GREEN)
        s.blit(hint, (bx + 30, by + 178))


# ----------------------------------------------------------------------------
# Хелперы
# ----------------------------------------------------------------------------
def sign(v):
    return (v > 0) - (v < 0)


def inside_board(c):
    return 0 <= c[0] < BOARD and 0 <= c[1] < BOARD


def inside(c):
    return inside_board(c)


def inside_board_or_off(c):
    """Разрешаем стоять чуть за краем (спавн), но не далеко."""
    return -2 <= c[0] <= BOARD + 1 and -2 <= c[1] <= BOARD + 1


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def cell_center_px(c):
    return (ORIGIN[0] + (c[0] + 0.5) * CELL, ORIGIN[1] + (c[1] + 0.5) * CELL)


def blocked_for_enemy(nx, ny, me, enemies):
    if not (-2 <= nx <= BOARD + 1 and -2 <= ny <= BOARD + 1):
        return True
    for e in enemies:
        if e is not me and e.alive and e.pos[0] == nx and e.pos[1] == ny:
            return True
    return False


def foereward_str(foe):
    return str(foe.reward)


# ----------------------------------------------------------------------------
def main():
    pygame.init()
    pygame.display.set_caption("Shotgun King style — King Roguelike")
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    clock = pygame.time.Clock()
    game = Game(screen)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                game.on_key(ev.key)
        game.update(dt)
        game.draw()
        pygame.display.flip()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
