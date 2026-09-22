package main

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/crypto/bcrypt"
)

func newLoginTestServer(t *testing.T, cfg AuthConfig) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)

	server := NewAppServer(NewXiaohongshuService(), cfg)
	return setupRoutes(server)
}

// postLogin 以表单方式提交登录，返回响应记录器。
func postLogin(t *testing.T, router *gin.Engine, user, pass, next string) *httptest.ResponseRecorder {
	t.Helper()

	form := url.Values{}
	form.Set("username", user)
	form.Set("password", pass)
	if next != "" {
		form.Set("next", next)
	}

	request := httptest.NewRequest(http.MethodPost, "/login", strings.NewReader(form.Encode()))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	return recorder
}

func sessionCookie(t *testing.T, recorder *httptest.ResponseRecorder) *http.Cookie {
	t.Helper()

	for _, cookie := range recorder.Result().Cookies() {
		if cookie.Name == sessionCookieName {
			return cookie
		}
	}

	return nil
}

func TestLoginPageIsPublicAndRenders(t *testing.T) {
	router := newLoginTestServer(t, AuthConfig{User: "me", Pass: "pw"})

	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/login", nil))

	assert.Equal(t, http.StatusOK, recorder.Code)
	assert.Contains(t, recorder.Header().Get("Content-Type"), "text/html")
	assert.Contains(t, recorder.Body.String(), `name="password"`)
}

func TestLoginRejectsWrongPassword(t *testing.T) {
	router := newLoginTestServer(t, AuthConfig{User: "me", Pass: "pw"})

	recorder := postLogin(t, router, "me", "wrong", "/health")

	assert.Equal(t, http.StatusFound, recorder.Code)
	assert.Contains(t, recorder.Header().Get("Location"), "error=bad")
	assert.Nil(t, sessionCookie(t, recorder), "登录失败不应签发会话 cookie")
}

// TestLoginAcceptsCorrectPasswordAndOpensSession 覆盖完整登录闭环：
// 提交账密 → 拿到 cookie → 用该 cookie 访问受保护接口。
func TestLoginAcceptsCorrectPasswordAndOpensSession(t *testing.T) {
	router := newLoginTestServer(t, AuthConfig{User: "me", Pass: "pw"})

	recorder := postLogin(t, router, "me", "pw", "/health")
	require.Equal(t, http.StatusFound, recorder.Code)
	assert.Equal(t, "/health", recorder.Header().Get("Location"))

	cookie := sessionCookie(t, recorder)
	require.NotNil(t, cookie, "登录成功应签发会话 cookie")
	assert.NotEmpty(t, cookie.Value)
	assert.True(t, cookie.HttpOnly, "会话 cookie 必须是 HttpOnly")
	assert.Equal(t, http.SameSiteLaxMode, cookie.SameSite)

	// 带 cookie 访问受保护接口应当放行。
	//
	// 注意：受保护端点全都是小红书业务接口，**每个都会真开浏览器**，
	// 不热缓存就会卡在 browser.go 的启动浏览器上（曾经让整个套件挂死 60 秒超时）。
	// 这里关心的是「鉴权有没有放行」，不是业务结果，所以先把缓存热上。
	saved := loginStatusCA
	loginStatusCA = &statusCache{ttl: time.Minute}
	loginStatusCA.set(&LoginStatusResponse{IsLoggedIn: false})
	defer func() { loginStatusCA = saved }()

	request := httptest.NewRequest(http.MethodGet, "/api/v1/login/status", nil)
	request.AddCookie(cookie)
	protected := httptest.NewRecorder()
	router.ServeHTTP(protected, request)

	assert.NotEqual(t, http.StatusUnauthorized, protected.Code)
}

// TestLoginAcceptsBcryptHashedPassword 覆盖 $2 前缀自动识别为 bcrypt hash。
func TestLoginAcceptsBcryptHashedPassword(t *testing.T) {
	hash, err := bcrypt.GenerateFromPassword([]byte("pw"), bcrypt.MinCost)
	require.NoError(t, err)

	router := newLoginTestServer(t, AuthConfig{User: "me", Pass: string(hash)})

	recorder := postLogin(t, router, "me", "pw", "/health")

	assert.Equal(t, http.StatusFound, recorder.Code)
	assert.Equal(t, "/health", recorder.Header().Get("Location"))
	assert.NotNil(t, sessionCookie(t, recorder))
}

func TestLogoutRevokesSession(t *testing.T) {
	router := newLoginTestServer(t, AuthConfig{User: "me", Pass: "pw"})

	cookie := sessionCookie(t, postLogin(t, router, "me", "pw", "/health"))
	require.NotNil(t, cookie)

	logout := httptest.NewRequest(http.MethodPost, "/logout", nil)
	logout.AddCookie(cookie)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, logout)
	assert.Equal(t, http.StatusFound, recorder.Code)

	// 同一个 cookie 再访问受保护接口应当被拒
	after := httptest.NewRequest(http.MethodGet, "/api/v1/login/status", nil)
	after.AddCookie(cookie)
	protected := httptest.NewRecorder()
	router.ServeHTTP(protected, after)

	assert.Equal(t, http.StatusUnauthorized, protected.Code)
}

// TestLoginRateLimitLocksAfterRepeatedFailures 固定公网部署最需要的防线：
// 连续失败到上限后必须被锁定，而不是无限重试。
func TestLoginRateLimitLocksAfterRepeatedFailures(t *testing.T) {
	router := newLoginTestServer(t, AuthConfig{User: "me", Pass: "pw"})

	for i := 0; i < loginMaxFailures; i++ {
		recorder := postLogin(t, router, "me", "wrong", "/health")
		assert.Contains(t, recorder.Header().Get("Location"), "error=bad")
	}

	recorder := postLogin(t, router, "me", "wrong", "/health")
	assert.Contains(t, recorder.Header().Get("Location"), "error=locked")

	// 即使密码正确，锁定期内也不放行
	correct := postLogin(t, router, "me", "pw", "/health")
	assert.Contains(t, correct.Header().Get("Location"), "error=locked")
	assert.Nil(t, sessionCookie(t, correct))
}

// TestSafeNextRejectsOpenRedirect 固定登录跳转只允许站内相对路径。
func TestSafeNextRejectsOpenRedirect(t *testing.T) {
	cases := map[string]string{
		"/health":            "/health",
		"/api/v1/feeds/list": "/api/v1/feeds/list",
		"":                   "/health",
		"//evil.com":         "/health",
		"http://evil.com":    "/health",
		`/\evil.com`:         "/health",
	}

	for input, want := range cases {
		assert.Equal(t, want, safeNext(input), "输入 %q", input)
	}
}

func TestAuthDisabledKeepsEndpointsOpen(t *testing.T) {
	router := newLoginTestServer(t, AuthConfig{})

	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/login/status", nil))

	assert.NotEqual(t, http.StatusUnauthorized, recorder.Code)
}
