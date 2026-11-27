#ifndef GAMEWIDGET_H
#define GAMEWIDGET_H

#include <QWidget>
#include <QTimer>
#include <QVector>
#include <QPoint>
#include <QString>
#include <QElapsedTimer>

// ---------- Константы поля ----------
constexpr int BOARD_SIZE = 12;          // поле 12x12
constexpr int CELL       = 56;          // размер клетки в пикселях

enum Side { SideTop, SideBottom, SideLeft, SideRight }; // сторона появления

// ---------- Сущности ----------
struct Pawn {
    QPoint pos;           // текущая клетка (логическая)
    int    hp      = 3;
    int    maxHp   = 3;
    bool   firstMove = true; // ещё не ходила — может сделать двойной шаг
    bool   dead    = false;
    Side   side    = SideTop; // с какой границы пришла (туда же и «домой»)

    // --- анимация ---
    QPointF renderPos {0, 0}; // экранные координаты центра (в клетках), плавно догоняют pos
    bool    renderInit = false;
    int     spawnDelay = 0;   // пешка появляется на этом такте, но входит позже
};

struct King {
    QPoint pos;
    int    hp     = 20;
    int    maxHp  = 20;
    int    attack = 2;    // урон по пешке за атаку
    QPointF renderPos {0, 0};
    bool    renderInit = false;
};

class GameWidget : public QWidget
{
    Q_OBJECT
public:
    explicit GameWidget(QWidget *parent = nullptr);

protected:
    void paintEvent(QPaintEvent *event) override;
    void keyPressEvent(QKeyEvent *event) override;

private slots:
    void tick();        // игровой такт: пешки ходят одновременно
    void animateFrame();// кадр анимации (~60 fps): плавное движение фигур

private:
    // --- логика ---
    void startNewRun();
    void spawnWave();                    // заспавнить порцию пешек с РАЗНЫХ сторон
    void tryAttack(int dx, int dy);      // попытка хода/атаки короля
    static bool insideBoard(const QPoint &p);
    Pawn* pawnAt(const QPoint &p);
    void  movePawns();                   // пешки делают ход по шахматным правилам
    static QPoint forwardDir(Side s);    // «вперёд» для пешки данной стороны
    static QPoint knockbackTarget(const QPoint &fromPawn, const QPoint &kingPos);
    static QPoint clampToField(const QPoint &p); // для отрисовки: не вылезаем далеко

    // --- отрисовка ---
    QRectF cellRectF(const QPointF &c) const;
    void drawBoard(QPainter &pr);
    void drawKing(QPainter &pr);
    void drawPawn(QPainter &pr, const Pawn &p);
    void drawHud(QPainter &pr);

    // --- состояние ---
    King             m_king;
    QVector<Pawn>    m_pawns;
    QTimer           m_timer;     // игровой такт
    QTimer           m_animTimer; // кадровый таймер анимации
    QElapsedTimer    m_clock;
    qint64           m_lastFrameMs = 0;
    int              m_turn      = 0;
    int              m_level     = 1;
    int              m_kills     = 0;
    QString          m_message;          // всплывающая строка
    int              m_messageTicks = 0;
    bool             m_gameOver  = false;

    static constexpr int TURN_MS  = 700; // длительность игрового такта
    static constexpr int ANIM_MS  = 16;  // ~60 fps
    static constexpr double MOVE_SPEED = 4.5; // клеток в секунду (плавно)
    static constexpr int MAX_PAWNS = 8;  // ограничение: пешек не должно быть много
};

#endif // GAMEWIDGET_H
