package main

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"html"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"
	"golang.org/x/crypto/bcrypt"
)

const (
	// sessionCookieName 浏览器会话 cookie 名。
	sessionCookieName = "xhs_session"
	// sessionTTL 会话有效期。单用户场景不需要持久化，服务重启即全部失效。
	sessionTTL = 12 * time.Hour
	// loginMaxFailures 同一 IP 在锁定窗口内允许的失败次数。
	loginMaxFailures = 5
	// loginLockWindow 达到失败上限后的锁定时长。
	loginLockWindow = 5 * time.Minute
	// failedLoginDelay 账密模式下失败固定延迟，给暴力破解加成本。
	failedLoginDelay = 300 * time.Millisecond
)

// AuthConfig 鉴权配置，两种凭据并存：
//   - Token：供机器客户端（MCP / curl）使用，走 Authorization: Bearer
//   - User/Pass：供浏览器使用，登录后换会话 cookie
//
// 两者都为空时完全关闭鉴权，与旧行为一致。
type AuthConfig struct {
	Token string
	User  string
	Pass  string // 明文；以 $2 开头时按 bcrypt hash 处理
}

// Enabled 是否启用了任一鉴权方式。
func (cfg AuthConfig) Enabled() bool {
	return cfg.Token != "" || cfg.User != ""
}

// PasswordLoginEnabled 是否启用了账号密码登录。
func (cfg AuthConfig) PasswordLoginEnabled() bool {
	return cfg.User != "" && cfg.Pass != ""
}

// verifyPassword 校验账号密码，用户名与密码都用恒定时间比较。
// 用户名错也照常走完密码校验，避免用响应时间区分「用户名是否存在」。
func (cfg AuthConfig) verifyPassword(user, pass string) bool {
	userOK := subtle.ConstantTimeCompare([]byte(user), []byte(cfg.User)) == 1

	var passOK bool
	if strings.HasPrefix(cfg.Pass, "$2") {
		passOK = bcrypt.CompareHashAndPassword([]byte(cfg.Pass), []byte(pass)) == nil
	} else {
		passOK = subtle.ConstantTimeCompare([]byte(pass), []byte(cfg.Pass)) == 1
	}

	return userOK && passOK
}

// sessionStore 内存会话表。
type sessionStore struct {
	mu       sync.Mutex
	sessions map[string]time.Time
}

func newSessionStore() *sessionStore {
	s := &sessionStore{sessions: make(map[string]time.Time)}
	go s.gc()

	return s
}

// gc 定期清理过期会话，避免内存无界增长。
func (s *sessionStore) gc() {
	ticker := time.NewTicker(10 * time.Minute)
	defer ticker.Stop()

	for range ticker.C {
		now := time.Now()
		s.mu.Lock()
		for sid, expireAt := range s.sessions {
			if now.After(expireAt) {
				delete(s.sessions, sid)
			}
		}
		s.mu.Unlock()
	}
}

func (s *sessionStore) create() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}

	sid := hex.EncodeToString(buf)

	s.mu.Lock()
	s.sessions[sid] = time.Now().Add(sessionTTL)
	s.mu.Unlock()

	return sid, nil
}

func (s *sessionStore) valid(sid string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	expireAt, ok := s.sessions[sid]
	if !ok {
		return false
	}
	if time.Now().After(expireAt) {
		delete(s.sessions, sid)
		return false
	}

	return true
}

func (s *sessionStore) revoke(sid string) {
	s.mu.Lock()
	delete(s.sessions, sid)
	s.mu.Unlock()
}

// loginLimiter 按来源 IP 限制登录失败次数，防止公网部署后被爆破。
// 用连接层 IP（RemoteIP）而不是 X-Forwarded-For，伪造请求头无法绕过限速。
type loginLimiter struct {
	mu      sync.Mutex
	records map[string]*loginRecord
}

type loginRecord struct {
	failures int
	lockedAt time.Time
}

func newLoginLimiter() *loginLimiter {
	return &loginLimiter{records: make(map[string]*loginRecord)}
}

// allow 判断该 IP 现在是否允许尝试登录，被锁定时返回剩余时长。
func (l *loginLimiter) allow(ip string) (bool, time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()

	rec, ok := l.records[ip]
	if !ok {
		return true, 0
	}

	if !rec.lockedAt.IsZero() {
		if remain := time.Until(rec.lockedAt.Add(loginLockWindow)); remain > 0 {
			return false, remain
		}
		// 锁定到期，重新计数
		delete(l.records, ip)
	}

	return true, 0
}

func (l *loginLimiter) fail(ip string) {
	l.mu.Lock()
	defer l.mu.Unlock()

	rec, ok := l.records[ip]
	if !ok {
		rec = &loginRecord{}
		l.records[ip] = rec
	}

	rec.failures++
	if rec.failures >= loginMaxFailures {
		rec.lockedAt = time.Now()
		logrus.Warnf("登录失败次数达上限，锁定该 IP %s 共 %s", ip, loginLockWindow)
	}
}

func (l *loginLimiter) reset(ip string) {
	l.mu.Lock()
	delete(l.records, ip)
	l.mu.Unlock()
}

// middleware 鉴权中间件：先认 Bearer Token，再认会话 cookie，都没过就拦掉。
func (cfg AuthConfig) middleware(sessions *sessionStore, limiter *loginLimiter) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !cfg.Enabled() {
			c.Next()
			return
		}

		// 机器客户端：Bearer Token
		if cfg.Token != "" {
			scheme, credentials, found := strings.Cut(c.GetHeader("Authorization"), " ")
			credentials = strings.TrimLeft(credentials, " ")
			if found && strings.EqualFold(scheme, "Bearer") &&
				subtle.ConstantTimeCompare([]byte(credentials), []byte(cfg.Token)) == 1 {
				c.Next()
				return
			}
		}

		// 浏览器：会话 cookie
		if sid, err := c.Cookie(sessionCookieName); err == nil && sessions.valid(sid) {
			c.Next()
			return
		}

		// 页面请求跳登录页，接口请求返回 JSON
		if isAPIPath(c.Request.URL.Path) {
			if cfg.Token != "" {
				c.Header("WWW-Authenticate", "Bearer")
			}
			respondError(c, http.StatusUnauthorized, "UNAUTHORIZED", "未授权", nil)
			c.Abort()
			return
		}

		c.Redirect(http.StatusFound, "/login?next="+url.QueryEscape(c.Request.URL.RequestURI()))
		c.Abort()
	}
}

// isAPIPath 区分接口请求与页面请求：只有 /api 与 /mcp 走 JSON 401。
func isAPIPath(path string) bool {
	return strings.HasPrefix(path, "/api/") || path == "/mcp" || strings.HasPrefix(path, "/mcp/")
}

// isHTTPS 判断当前请求是否经由 HTTPS，用于决定 cookie 是否带 Secure。
// 直接暴露时看 TLS；部署在 TLS 终止代理后面时看 X-Forwarded-Proto。
func isHTTPS(c *gin.Context) bool {
	return c.Request.TLS != nil || strings.EqualFold(c.GetHeader("X-Forwarded-Proto"), "https")
}

// safeNext 校验登录后的跳转目标，只允许站内相对路径，避免开放重定向。
func safeNext(next string) string {
	if next == "" || !strings.HasPrefix(next, "/") ||
		strings.HasPrefix(next, "//") || strings.Contains(next, "\\") {
		return "/health"
	}

	return next
}

// setSessionCookie 写入会话 cookie。
// SameSite=Lax 足够：所有会改状态的接口都是 POST / DELETE，跨站请求带不上这个 cookie。
func setSessionCookie(c *gin.Context, sid string) {
	http.SetCookie(c.Writer, &http.Cookie{
		Name:     sessionCookieName,
		Value:    sid,
		Path:     "/",
		MaxAge:   int(sessionTTL.Seconds()),
		HttpOnly: true,
		Secure:   isHTTPS(c),
		SameSite: http.SameSiteLaxMode,
	})
}

// handleLoginPage 渲染登录页。若已登录则直接跳到目标页。
func (s *AppServer) handleLoginPage(c *gin.Context) {
	if sid, err := c.Cookie(sessionCookieName); err == nil && s.sessions.valid(sid) {
		c.Redirect(http.StatusFound, safeNext(c.Query("next")))
		return
	}

	next := safeNext(c.Query("next"))
	c.Header("Content-Type", "text/html; charset=utf-8")
	c.String(http.StatusOK, loginPageHTML(next, c.Query("error")))
}

// handleLoginSubmit 校验账号密码，成功则签发会话 cookie。
func (s *AppServer) handleLoginSubmit(c *gin.Context) {
	if !s.auth.PasswordLoginEnabled() {
		respondError(c, http.StatusNotFound, "NOT_FOUND", "未启用账号密码登录", nil)
		return
	}

	next := safeNext(c.PostForm("next"))
	ip := c.RemoteIP()

	if ok, remain := s.limiter.allow(ip); !ok {
		logrus.Warnf("登录被限速拦截，来源 %s，剩余 %s", ip, remain.Round(time.Second))
		c.Header("Retry-After", strconv.Itoa(int(remain.Seconds())+1))
		c.Redirect(http.StatusFound, "/login?error=locked&next="+url.QueryEscape(next))
		return
	}

	if !s.auth.verifyPassword(c.PostForm("username"), c.PostForm("password")) {
		// 固定延迟，抬高暴力破解成本
		time.Sleep(failedLoginDelay)
		s.limiter.fail(ip)
		logrus.Warnf("登录失败，来源 %s，用户名 %q", ip, c.PostForm("username"))
		c.Redirect(http.StatusFound, "/login?error=bad&next="+url.QueryEscape(next))
		return
	}

	sid, err := s.sessions.create()
	if err != nil {
		respondError(c, http.StatusInternalServerError, "INTERNAL_ERROR", "创建会话失败", err)
		return
	}

	s.limiter.reset(ip)
	setSessionCookie(c, sid)
	logrus.Infof("登录成功，来源 %s，用户名 %q", ip, s.auth.User)

	c.Redirect(http.StatusFound, next)
}

// handleLogout 注销当前会话。
func (s *AppServer) handleLogout(c *gin.Context) {
	if sid, err := c.Cookie(sessionCookieName); err == nil {
		s.sessions.revoke(sid)
	}

	http.SetCookie(c.Writer, &http.Cookie{
		Name:     sessionCookieName,
		Value:    "",
		Path:     "/",
		MaxAge:   -1,
		HttpOnly: true,
		Secure:   isHTTPS(c),
		SameSite: http.SameSiteLaxMode,
	})

	c.Redirect(http.StatusFound, "/login")
}

// loginPageHTML 返回登录页。内联样式、无外部资源，手机浏览器直接可用。
func loginPageHTML(next, errCode string) string {
	var tip string
	switch errCode {
	case "bad":
		tip = `<p class="err">账号或密码不正确</p>`
	case "locked":
		tip = `<p class="err">失败次数过多，请稍后再试</p>`
	}

	return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>登录 · xiaohongshu-mcp</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
         background: #fbf7f0; color: #2b2b2b;
         font: 15px/1.6 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; padding: 24px; }
  form { width: 100%; max-width: 340px; background: #fff; border: 1px solid #ece6dc;
         border-radius: 14px; padding: 26px 22px; box-shadow: 0 6px 28px rgba(0,0,0,.05); }
  h1 { margin: 0 0 4px; font-size: 17px; }
  .sub { margin: 0 0 20px; font-size: 12.5px; color: #807a72; }
  label { display: block; font-size: 12.5px; color: #807a72; margin: 14px 0 6px; }
  input { width: 100%; padding: 11px 12px; font-size: 15px; border: 1px solid #ddd6ca;
          border-radius: 9px; background: #fff; color: inherit; }
  input:focus { outline: none; border-color: #ff5c5c; }
  button { width: 100%; margin-top: 20px; padding: 12px; font-size: 15px; font-weight: 600;
           color: #fff; background: #ff5c5c; border: 0; border-radius: 9px; cursor: pointer; }
  button:active { background: #e84a4a; }
  .err { margin: 0 0 4px; padding: 9px 12px; font-size: 13px; color: #c0392b;
         background: #fdeceb; border-radius: 8px; }
  @media (prefers-color-scheme: dark) {
    body { background: #14120f; color: #eae6e0; }
    form { background: #1d1a17; border-color: #302b26; }
    input { background: #14120f; border-color: #3a342e; }
    .err { background: #3a1f1d; color: #ff9a90; }
  }
</style>
</head>
<body>
<form method="post" action="/login">
  <h1>xiaohongshu-mcp</h1>
  <p class="sub">请登录后继续</p>
  ` + tip + `
  <label for="u">账号</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none" required>
  <label for="p">密码</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <input type="hidden" name="next" value="` + html.EscapeString(next) + `">
  <button type="submit">登录</button>
</form>
</body>
</html>`
}
