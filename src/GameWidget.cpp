#include "GameWidget.h"

#include <QPainter>
#include <QPaintEvent>
#include <QKeyEvent>
#include <QRandomGenerator>
#include <QtMath>
#include <algorithm>

// Смещение координат поля внутри виджета (слева панель HUD)
static const QPoint ORIGIN(20, 90);

static int boardPx() { return BOARD_SIZE * CELL; }

// ============================================================================
GameWidget::GameWidget(QWidget *parent) : QWidget(parent)
{
    setFocusPolicy(Qt::StrongFocus);
    setWindowTitle("King Roguelike — бета 0.2 (плавная анимация)");
    setFixedSize(ORIGIN.x() + boardPx() + 300, std::max(ORIGIN.y() + boardPx(), 560) + 20);

    connect(&m_timer,     &QTimer::timeout, this, &GameWidget::tick);
    connect(&m_animTimer, &QTimer::timeout, this, &GameWidget::animateFrame);
    m_clock.start();
    m_lastFrameMs = m_clock.elapsed();

    startNewRun();
    m_timer.start(TURN_MS);
    m_animTimer.setTimerType(Qt::PreciseTimer);
    m_animTimer.start(ANIM_MS);
}

void GameWidget::startNewRun()
{
    m_king.pos   = QPoint(BOARD_SIZE / 2, BOARD_SIZE / 2); // центр поля
    m_king.hp    = m_king.maxHp;
    m_king.renderInit = false;
    m_pawns.clear();
    m_turn     = 0;
    m_level    = 1;
    m_kills    = 0;
    m_gameOver = false;
    m_message      = "Уровень 1: пешки наступают со всех сторон! WASD/стрелки.";
    m_messageTicks = 8;
    spawnWave();
}

bool GameWidget::insideBoard(const QPoint &p)
{
    return p.x() >= 0 && p.x() < BOARD_SIZE && p.y() >= 0 && p.y() < BOARD_SIZE;
}

Pawn* GameWidget::pawnAt(const QPoint &p)
{
    for (auto &pw : m_pawns)
        if (!pw.dead && pw.pos == p)
            return &pw;
    return nullptr;
}

// Направление «вперёд» (к центру поля) для пешки, пришедшей с данной стороны.
QPoint GameWidget::forwardDir(Side s)
{
    switch (s) {
    case SideTop:    return QPoint( 0,  1); // сверху — идёт вниз
    case SideBottom: return QPoint( 0, -1); // снизу — идёт вверх
    case SideLeft:   return QPoint( 1,  0); // слева — идёт вправо
    case SideRight:  return QPoint(-1,  0); // справа — идёт влево
    }
    return QPoint(0, 1);
}

// Точка, куда отлетает пешка после удара короля: на 2 клетки назад
// (от короля, вдоль линии король->пешка).
QPoint GameWidget::knockbackTarget(const QPoint &fromPawn, const QPoint &kingPos)
{
    QPoint d = fromPawn - kingPos;          // вектор от короля к пешке
    auto sgn = [](int v){ return v > 0 ? 1 : (v < 0 ? -1 : 0); };
    QPoint step(sgn(d.x()), sgn(d.y()));
    if (step.isNull()) step = QPoint(0, -1); // страховка
    return fromPawn + step * 2;             // отлёт на 2 клетки
}

// ----------------------------------------------------------------------------
// Спавн: небольшая порция пешек появляется за границами поля С РАЗНЫХ СТОРОН.
// Пешка с каждой стороны ходит «вперёд» к центру по шахматным правилам
// (шаг вперёд, двойной шаг с начальной позиции, рубит по диагоналям вперёд).
// ----------------------------------------------------------------------------
void GameWidget::spawnWave()
{
    auto *rg = QRandomGenerator::global();

    // сколько можно доспавнить (не больше MAX_PAWNS живых одновременно)
    int alive = 0;
    for (const auto &p : m_pawns) if (!p.dead) ++alive;
    int want = std::min(2 + m_level, MAX_PAWNS - alive); // было 3+level*2 — стало заметно меньше
    if (want <= 0) return;

    // выбираем 2 случайные разные стороны для этой волны — разнообразие осад
    QVector<Side> sides = { SideTop, SideBottom, SideLeft, SideRight };
    std::shuffle(sides.begin(), sides.end(), *rg);
    int sideCount = std::min(2, (int)sides.size());

    for (int i = 0; i < want; ++i) {
        Side s = sides[i % sideCount];
        Pawn p;
        p.side = s;
        const int off = 1 + rg->bounded(2); // на 1..2 клетки за границей
        switch (s) {
        case SideTop:    p.pos = QPoint(rg->bounded(BOARD_SIZE), -off); break;
        case SideBottom: p.pos = QPoint(rg->bounded(BOARD_SIZE), BOARD_SIZE - 1 + off); break;
        case SideLeft:   p.pos = QPoint(-off, rg->bounded(BOARD_SIZE)); break;
        case SideRight:  p.pos = QPoint(BOARD_SIZE - 1 + off, rg->bounded(BOARD_SIZE)); break;
        }
        p.maxHp = 2 + m_level;
        p.hp    = p.maxHp;
        p.firstMove = true;
        m_pawns.push_back(p);
    }
}

// ----------------------------------------------------------------------------
// Кадр анимации (~60 fps): renderPos каждой фигуры плавно догоняет pos.
// Движение равномерное с лёгким замедлением в конце (ease-out), поэтому
// шаги, двойные шаги и отбрасывание выглядят гладко.
// ----------------------------------------------------------------------------
void GameWidget::animateFrame()
{
    const qint64 now = m_clock.elapsed();
    double dt = (now - m_lastFrameMs) / 1000.0;
    m_lastFrameMs = now;
    if (dt <= 0) dt = 0.016;
    if (dt > 0.1) dt = 0.1; // защита от рывков при лагах

    auto approach = [dt](QPointF &rp, const QPoint &target) {
        QPointF tgt(target.x(), target.y());
        QPointF diff = tgt - rp;
        double dist = std::hypot(diff.x(), diff.y());
        if (dist < 0.005) { rp = tgt; return; }
        // скорость пропорциональна расстоянию (ease-out), но не ниже минимума
        double speed = MOVE_SPEED * qMax(0.35, qMin(1.0, dist));
        double move = speed * dt;
        if (move >= dist) rp = tgt;
        else rp += diff / dist * move;
    };

    bool moved = false;
    if (!m_king.renderInit) {
        m_king.renderPos = QPointF(m_king.pos.x(), m_king.pos.y());
        m_king.renderInit = true;
    } else if (m_king.renderPos != QPointF(m_king.pos.x(), m_king.pos.y())) {
        approach(m_king.renderPos, m_king.pos);
        moved = true;
    }

    for (auto &p : m_pawns) {
        if (p.dead) continue;
        if (!p.renderInit) {
            p.renderPos = QPointF(p.pos.x(), p.pos.y());
            p.renderInit = true;
        } else if (p.renderPos != QPointF(p.pos.x(), p.pos.y())) {
            approach(p.renderPos, p.pos);
            moved = true;
        }
    }

    if (moved || m_messageTicks > 0) update();
}

// ----------------------------------------------------------------------------
// Один такт: раз в TURN_MS мс все пешки ходят ОДНОВРЕМЕННО.
// ----------------------------------------------------------------------------
void GameWidget::tick()
{
    if (m_gameOver) { update(); return; }

    ++m_turn;
    movePawns();

    // новая волна каждые 14 тактов, уровень растёт
    if (m_turn % 14 == 0) {
        ++m_level;
        spawnWave();
        m_message = QString("Уровень %1! Волна усиливается...").arg(m_level);
        m_messageTicks = 6;
    }

    // если всех убили — подкрепление (скромное)
    bool anyAlive = std::any_of(m_pawns.begin(), m_pawns.end(),
                                [](const Pawn &p){ return !p.dead; });
    if (!anyAlive) {
        spawnWave();
        m_message = "Волна отбита! Подходят новые силы противника.";
        m_messageTicks = 6;
    }

    // чистим мёртвых
    m_pawns.erase(std::remove_if(m_pawns.begin(), m_pawns.end(),
                                 [](const Pawn &p){ return p.dead; }),
                  m_pawns.end());

    update();
}

void GameWidget::movePawns()
{
    for (auto &p : m_pawns) {
        if (p.dead) continue;

        const QPoint fwd = forwardDir(p.side);
        const QPoint rgt(fwd.y(), -fwd.x()); // перпендикуляр для диагональных атак

        // пешка, зашедшая за противоположный край, уходит из игры
        if (p.side == SideTop    && p.pos.y() >= BOARD_SIZE) { p.dead = true; continue; }
        if (p.side == SideBottom && p.pos.y() < 0)           { p.dead = true; continue; }
        if (p.side == SideLeft   && p.pos.x() >= BOARD_SIZE) { p.dead = true; continue; }
        if (p.side == SideRight  && p.pos.x() < 0)           { p.dead = true; continue; }

        // 1) Атака: если на одной из двух диагоналей «вперёд» стоит король — рубим
        QPoint l = p.pos + fwd + rgt;
        QPoint r = p.pos + fwd - rgt;
        if (l == m_king.pos || r == m_king.pos) {
            m_king.hp -= 1;
            m_message = "Пешка ударила короля! -1 HP";
            m_messageTicks = 4;
            if (m_king.hp <= 0) {
                m_gameOver = true;
                m_message = QString("GAME OVER. Продержался %1 тактов, убил %2 пешек. R — заново.")
                                .arg(m_turn).arg(m_kills);
            }
            continue; // атака заменяет ход
        }

        // 2) Обычный ход вперёд на 1 (или 2, если первый ход и путь свободен)
        QPoint one = p.pos + fwd;
        QPoint two = p.pos + fwd * 2;

        bool oneFree = !pawnAt(one) && !(one == m_king.pos);
        bool twoFree = !pawnAt(two) && !(two == m_king.pos);

        if (p.firstMove && twoFree && oneFree) {
            p.pos = two;
            p.firstMove = false;
        } else if (oneFree) {
            p.pos = one;
            p.firstMove = false;
        }
        // иначе стоит (заблокирована)
    }
}

// ----------------------------------------------------------------------------
// Ход игрока: клавиши. Если на целевой клетке пешка — атака (урон + отбрасывание
// на 2 клетки назад). Король ходит строго как в шахматах: на 1 клетку в любую
// сторону.
// ----------------------------------------------------------------------------
void GameWidget::tryAttack(int dx, int dy)
{
    if (m_gameOver) return;

    QPoint target = m_king.pos + QPoint(dx, dy);
    if (!insideBoard(target)) return;

    Pawn *victim = pawnAt(target);
    if (victim) {
        // --- атака: не двигаемся, наносим урон и отбрасываем ---
        victim->hp -= m_king.attack;
        victim->pos = knockbackTarget(victim->pos, m_king.pos);
        victim->firstMove = false; // после отбрасывания «сбивается»
        if (victim->hp <= 0) {
            victim->dead = true;
            ++m_kills;
            m_message = "Пешка уничтожена!";
        } else {
            m_message = "Удар! Пешка отброшена на 2 клетки.";
        }
        m_messageTicks = 4;
    } else {
        // --- обычный ход короля ---
        m_king.pos = target;
    }
    update(); // ход игрока происходит сразу, анимация доедет сама
}

void GameWidget::keyPressEvent(QKeyEvent *e)
{
    if (m_gameOver && (e->key() == Qt::Key_R)) { startNewRun(); return; }

    switch (e->key()) {
    case Qt::Key_W: case Qt::Key_Up:     tryAttack( 0, -1); break;
    case Qt::Key_S: case Qt::Key_Down:   tryAttack( 0,  1); break;
    case Qt::Key_A: case Qt::Key_Left:   tryAttack(-1,  0); break;
    case Qt::Key_D: case Qt::Key_Right:  tryAttack( 1,  0); break;
    // диагонали короля: Q/E/Z/C
    case Qt::Key_Q: tryAttack(-1, -1); break;
    case Qt::Key_E: tryAttack( 1, -1); break;
    case Qt::Key_Z: tryAttack(-1,  1); break;
    case Qt::Key_C: tryAttack( 1,  1); break;
    default: QWidget::keyPressEvent(e);
    }
}

// ============================================================================
// Отрисовка
// ============================================================================
QRectF GameWidget::cellRectF(const QPointF &c) const
{
    return QRectF(ORIGIN.x() + c.x() * CELL, ORIGIN.y() + c.y() * CELL, CELL, CELL);
}

void GameWidget::paintEvent(QPaintEvent *)
{
    QPainter pr(this);
    pr.setRenderHint(QPainter::Antialiasing);
    pr.fillRect(rect(), QColor(24, 24, 30));

    drawBoard(pr);

    // фигуры клиппим по границе доски — пешки красиво «выезжают» из-за края
    pr.save();
    pr.setClipRect(QRectF(ORIGIN.x(), ORIGIN.y(), boardPx(), boardPx()));
    for (const auto &p : m_pawns)
        if (!p.dead) drawPawn(pr, p);
    drawKing(pr);
    pr.restore();

    drawHud(pr);
}

void GameWidget::drawBoard(QPainter &pr)
{
    for (int y = 0; y < BOARD_SIZE; ++y)
        for (int x = 0; x < BOARD_SIZE; ++x) {
            bool dark = (x + y) % 2 == 0;
            pr.fillRect(cellRectF(QPointF(x, y)),
                        dark ? QColor(72, 86, 74) : QColor(150, 160, 140));
        }
    pr.setPen(QPen(QColor(200, 200, 200), 2));
    pr.drawRect(ORIGIN.x(), ORIGIN.y(), boardPx(), boardPx());
}

void GameWidget::drawKing(QPainter &pr)
{
    QRectF r = cellRectF(m_king.renderPos).adjusted(6, 6, -6, -6);
    pr.setBrush(QColor(240, 200, 60));
    pr.setPen(QPen(QColor(90, 70, 10), 2));
    pr.drawEllipse(r);
    pr.setPen(QPen(QColor(60, 45, 0), 3));
    QFont f = pr.font(); f.setPointSize(18); f.setBold(true); pr.setFont(f);
    pr.drawText(cellRectF(m_king.renderPos), Qt::AlignCenter, "\u265A"); // ♚
}

void GameWidget::drawPawn(QPainter &pr, const Pawn &p)
{
    QRectF cell = cellRectF(p.renderPos);
    QRectF r = cell.adjusted(10, 10, -10, -10);
    pr.setBrush(QColor(60, 60, 66));
    pr.setPen(QPen(QColor(10, 10, 12), 2));
    pr.drawEllipse(r);
    pr.setPen(Qt::white);
    QFont f = pr.font(); f.setPointSize(16); pr.setFont(f);
    pr.drawText(cell, Qt::AlignCenter, "\u265F"); // ♟

    // полоска HP
    QRectF hpBar = cell.adjusted(8, CELL - 14, -8, -8);
    pr.fillRect(hpBar, QColor(80, 20, 20));
    float frac = float(p.hp) / float(p.maxHp);
    pr.fillRect(QRectF(hpBar.x(), hpBar.y(), hpBar.width() * qBound(0.0f, frac, 1.0f), hpBar.height()),
                QColor(220, 60, 60));
}

void GameWidget::drawHud(QPainter &pr)
{
    int hx = ORIGIN.x() + boardPx() + 24;

    pr.setPen(Qt::white);
    QFont f = pr.font(); f.setPointSize(14); f.setBold(true); pr.setFont(f);
    pr.drawText(hx, 110, "KING ROGUELIKE");
    f.setPointSize(10); f.setBold(false); pr.setFont(f);

    int yy = 145;
    pr.drawText(hx, yy, QString("Уровень: %1").arg(m_level));           yy += 24;
    pr.drawText(hx, yy, QString("Такт: %1").arg(m_turn));               yy += 24;
    pr.drawText(hx, yy, QString("Убито пешек: %1").arg(m_kills));       yy += 30;

    // HP бар короля
    pr.drawText(hx, yy, "Здоровье короля:");                            yy += 10;
    QRect bar(hx, yy, 220, 22);
    pr.fillRect(bar, QColor(80, 20, 20));
    float frac = float(m_king.hp) / m_king.maxHp;
    pr.fillRect(QRect(bar.x(), bar.y(), int(bar.width() * qBound(0.0f, frac, 1.0f)), bar.height()),
                QColor(240, 200, 60));
    pr.setPen(Qt::black);
    pr.drawText(bar, Qt::AlignCenter, QString("%1 / %2").arg(m_king.hp).arg(m_king.maxHp));
    pr.setPen(Qt::white);
    yy += 46;

    QStringList help;
    help << QStringLiteral("WASD / стрелки — ход короля,")
         << QStringLiteral("Q/E/Z/C — ходы по диагоналям.")
         << QStringLiteral("Ход на клетку с пешкой = атака:")
         << QStringLiteral("урон %1, отбрасывание на 2 клетки.").arg(m_king.attack)
         << QString()
         << QStringLiteral("Пешки появляются с разных сторон")
         << QStringLiteral("поля и ходят по шахматным правилам:")
         << QStringLiteral("шаг вперёд, рубят по диагонали.")
         << QStringLiteral("Раз в %1 мс ходят одновременно.").arg(TURN_MS)
         << QString()
         << QStringLiteral("R — начать заново после смерти.");
    for (const auto &line : help) { pr.drawText(hx, yy, line); yy += 20; }

    // сообщение поверх поля
    if (m_messageTicks > 0) {
        --m_messageTicks;
        pr.setPen(QColor(255, 230, 120));
        QFont mf = pr.font(); mf.setPointSize(12); mf.setBold(true); pr.setFont(mf);
        pr.drawText(ORIGIN.x(), ORIGIN.y() - 12, m_message);
    }

    if (m_gameOver) {
        pr.fillRect(ORIGIN.x(), ORIGIN.y(), boardPx(), boardPx(), QColor(0, 0, 0, 170));
        pr.setPen(Qt::red);
        QFont gf = pr.font(); gf.setPointSize(28); gf.setBold(true); pr.setFont(gf);
        pr.drawText(QRect(ORIGIN.x(), ORIGIN.y() + boardPx()/2 - 60, boardPx(), 120),
                    Qt::AlignCenter, "GAME OVER\nR — заново");
    }
}
