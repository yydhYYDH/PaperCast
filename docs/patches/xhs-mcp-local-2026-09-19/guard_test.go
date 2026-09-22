package main

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// --- browserBudget ---------------------------------------------------------

func TestBrowserBudgetExhaustsAtMax(t *testing.T) {
	b := &browserBudget{max: 3, window: time.Minute}

	if b.Exhausted() {
		t.Fatal("空预算不应判定为用尽")
	}

	for i := 0; i < 3; i++ {
		b.Record()
	}
	if !b.Exhausted() {
		t.Fatal("记满 3 次后应判定为用尽")
	}

	used, max, window := b.Snapshot()
	if used != 3 || max != 3 || window != time.Minute {
		t.Fatalf("Snapshot = (%d, %d, %s)，期望 (3, 3, 1m)", used, max, window)
	}
}

func TestBrowserBudgetTrimsExpiredMarks(t *testing.T) {
	b := &browserBudget{max: 2, window: 20 * time.Millisecond}

	b.Record()
	b.Record()
	if !b.Exhausted() {
		t.Fatal("窗口内记满应判定为用尽")
	}

	time.Sleep(30 * time.Millisecond)
	if b.Exhausted() {
		t.Fatal("窗口外的记录应被丢弃，不应再判定为用尽")
	}
	if used, _, _ := b.Snapshot(); used != 0 {
		t.Fatalf("过期后已用数应为 0，实际 %d", used)
	}
}

func TestBrowserBudgetDisabledWhenMaxNonPositive(t *testing.T) {
	for _, max := range []int{0, -1} {
		b := &browserBudget{max: max, window: time.Minute}
		for i := 0; i < 10; i++ {
			b.Record()
		}
		if b.Exhausted() {
			t.Fatalf("max=%d 表示不限流，不应判定为用尽", max)
		}
	}
}

// --- statusCache -----------------------------------------------------------

func TestStatusCacheHitThenExpire(t *testing.T) {
	c := &statusCache{ttl: 40 * time.Millisecond}
	c.set(&LoginStatusResponse{IsLoggedIn: true, Username: "momo"})

	got, ok := c.get()
	if !ok {
		t.Fatal("未过期应命中缓存")
	}
	if !got.IsLoggedIn || got.Username != "momo" {
		t.Fatalf("缓存内容不对: %+v", got)
	}

	time.Sleep(50 * time.Millisecond)
	if _, ok := c.get(); ok {
		t.Fatal("过期后不应命中")
	}
}

func TestStatusCacheInvalidate(t *testing.T) {
	c := &statusCache{ttl: time.Minute}
	c.set(&LoginStatusResponse{IsLoggedIn: true})
	c.invalidate()

	if _, ok := c.get(); ok {
		t.Fatal("invalidate 后不应命中")
	}
}

func TestStatusCacheReturnsCopy(t *testing.T) {
	c := &statusCache{ttl: time.Minute}
	c.set(&LoginStatusResponse{IsLoggedIn: true, Username: "momo"})

	got, _ := c.get()
	got.Username = "被调用方改坏了"

	again, _ := c.get()
	if again.Username != "momo" {
		t.Fatalf("调用方修改返回值污染了缓存本体: %q", again.Username)
	}
}

func TestStatusCacheDisabledWhenTTLNonPositive(t *testing.T) {
	c := &statusCache{ttl: 0}
	c.set(&LoginStatusResponse{IsLoggedIn: true})

	if _, ok := c.get(); ok {
		t.Fatal("ttl<=0 表示不缓存，不应命中")
	}
}

// --- envInt ----------------------------------------------------------------

func TestEnvInt(t *testing.T) {
	t.Setenv("XHS_TEST_INT", "42")
	if got := envInt("XHS_TEST_INT", 7); got != 42 {
		t.Fatalf("envInt = %d，期望 42", got)
	}

	t.Setenv("XHS_TEST_INT", "不是数字")
	if got := envInt("XHS_TEST_INT", 7); got != 7 {
		t.Fatalf("非法值应回退默认值，实际 %d", got)
	}

	if got := envInt("XHS_TEST_INT_NEVER_SET", 7); got != 7 {
		t.Fatalf("未设置应返回默认值，实际 %d", got)
	}
}

// --- accessBudgetMiddleware -------------------------------------------------

func TestAccessBudgetMiddleware(t *testing.T) {
	gin.SetMode(gin.TestMode)

	orig := xhsBudget
	defer func() { xhsBudget = orig }()

	newRouter := func() *gin.Engine {
		r := gin.New()
		r.Use(accessBudgetMiddleware())
		r.GET("/api/v1/login/status", func(c *gin.Context) { c.String(http.StatusOK, "ok") })
		return r
	}
	do := func(r *gin.Engine) int {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/v1/login/status", nil))
		return w.Code
	}

	// 预算未用尽：放行
	xhsBudget = &browserBudget{max: 2, window: time.Minute}
	if code := do(newRouter()); code != http.StatusOK {
		t.Fatalf("预算充足应放行，实际 %d", code)
	}

	// 预算用尽：拒绝
	xhsBudget.Record()
	xhsBudget.Record()
	if code := do(newRouter()); code != http.StatusTooManyRequests {
		t.Fatalf("预算用尽应返回 429，实际 %d", code)
	}

	// 不限流（max<=0）：永远放行
	xhsBudget = &browserBudget{max: 0, window: time.Minute}
	for i := 0; i < 5; i++ {
		xhsBudget.Record()
	}
	if code := do(newRouter()); code != http.StatusOK {
		t.Fatalf("max<=0 表示不限流，应放行，实际 %d", code)
	}
}

// TestStatusCachePreventsBrowserLaunch 是这次改动的核心断言：
// 缓存命中时不应走到 newBrowser()，因此不应消耗访问预算。
func TestStatusCachePreventsBrowserLaunch(t *testing.T) {
	origBudget := xhsBudget
	defer func() { xhsBudget = origBudget }()

	xhsBudget = &browserBudget{max: 100, window: time.Minute}

	c := &statusCache{ttl: time.Minute}
	c.set(&LoginStatusResponse{IsLoggedIn: false})

	before, _, _ := xhsBudget.Snapshot()
	for i := 0; i < 20; i++ { // 模拟 20 次轮询
		if _, ok := c.get(); !ok {
			t.Fatal("应命中缓存")
		}
	}
	after, _, _ := xhsBudget.Snapshot()

	if after != before {
		t.Fatalf("缓存命中不应消耗访问预算，实际从 %d 变成 %d", before, after)
	}
}

func TestStatusCacheDefaultTTLIsFiveMinutes(t *testing.T) {
	t.Setenv("XHS_STATUS_TTL_SECONDS", "") // 清空即走默认值

	if got := newStatusCache().ttl; got != 300*time.Second {
		t.Fatalf("默认 TTL 应为 300s，实际 %s", got)
	}
}

// TestCheckLoginStatusServesFromCache 断言服务层：缓存命中时不开浏览器。
// 用真实 Service 走一遍，避免「缓存测通了、但服务层绕过了缓存」这种漏网。
func TestCheckLoginStatusServesFromCache(t *testing.T) {
	saved := loginStatusCA
	defer func() { loginStatusCA = saved }()

	loginStatusCA = &statusCache{ttl: time.Minute}
	loginStatusCA.set(&LoginStatusResponse{IsLoggedIn: true, Username: "来自缓存"})

	svc := &XiaohongshuService{}
	got, err := svc.CheckLoginStatus(context.Background())
	if err != nil {
		t.Fatalf("缓存命中时不应报错: %v", err)
	}
	if got.Username != "来自缓存" {
		t.Fatalf("应直接返回缓存内容，实际 %+v", got)
	}
}

// TestStatusCacheSingleFlight 是「窗口成对弹出」那个 bug 的回归测试。
// TTL 到期那一瞬间同时到达的两个请求，必须只有一个取得探测权，
// 否则两个都会去 newBrowser()，用户就看到两个浏览器窗口一起弹。
func TestStatusCacheSingleFlight(t *testing.T) {
	c := &statusCache{ttl: time.Minute}

	cached, f1, mine := c.begin()
	if cached != nil || !mine || f1 == nil {
		t.Fatalf("首次未命中应取得探测权：cached=%v mine=%v", cached, mine)
	}

	// 第二个并发调用：不该再取得探测权，而应挂到同一个 flight 上
	cached2, f2, mine2 := c.begin()
	if cached2 != nil || mine2 {
		t.Fatal("已有探测在跑时又发了一次探测 —— 这正是成对弹窗的成因")
	}
	if f2 != f1 {
		t.Fatal("第二个调用应等到同一个 flight")
	}

	c.end(f1, &LoginStatusResponse{IsLoggedIn: true, Username: "单飞"}, nil)

	select {
	case <-f2.done:
	case <-time.After(time.Second):
		t.Fatal("end 后等待者应被唤醒")
	}
	if f2.resp == nil || f2.resp.Username != "单飞" {
		t.Fatalf("等待者应复用探测结果，实际 %+v", f2.resp)
	}

	// 探测结果要回填缓存，后续调用直接命中
	if got, ok := c.get(); !ok || got.Username != "单飞" {
		t.Fatalf("end 后应回填缓存，实际 ok=%v %+v", ok, got)
	}
}

func TestStatusCacheSingleFlightOnError(t *testing.T) {
	c := &statusCache{ttl: time.Minute}

	_, f1, mine := c.begin()
	if !mine {
		t.Fatal("首次应取得探测权")
	}
	_, f2, mine2 := c.begin()
	if mine2 {
		t.Fatal("不应重复探测")
	}

	boom := errors.New("探测失败")
	c.end(f1, nil, boom)
	<-f2.done

	if f2.err != boom {
		t.Fatalf("等待者应拿到同一个错误，实际 %v", f2.err)
	}
	// 失败不能写进缓存，否则错误状态会被缓存一整个 TTL
	if _, ok := c.get(); ok {
		t.Fatal("探测失败时不应回填缓存")
	}
	// 失败后必须能重新探测（flight 要清掉）
	if _, _, mine := c.begin(); !mine {
		t.Fatal("失败后应能重新取得探测权")
	}
}

// TestStatusCachePeekIgnoresTTL 覆盖「轮询路径不许主动开浏览器」这个约定：
// peek 必须无视 TTL 也能拿到上次结果，且返回副本、带上年龄。
func TestStatusCachePeekIgnoresTTL(t *testing.T) {
	c := &statusCache{ttl: 0} // ttl<=0 时 get 永远不命中
	c.set(&LoginStatusResponse{IsLoggedIn: true, Username: "旧结果"})

	if _, ok := c.get(); ok {
		t.Fatal("ttl<=0 时 get 不应命中")
	}

	got, age, ok := c.peek()
	if !ok || got == nil || got.Username != "旧结果" {
		t.Fatalf("peek 应无视 TTL 返回上次结果，实际 ok=%v %+v", ok, got)
	}
	if age < 0 {
		t.Fatalf("年龄不应为负，实际 %s", age)
	}

	// 必须是副本：改返回值不能污染缓存本体
	got.Username = "被改了"
	if again, _, _ := c.peek(); again.Username != "旧结果" {
		t.Fatal("peek 应返回副本")
	}
}

// TestCheckLoginStatusReusesStaleResultInsteadOfProbing 是「窗口反复弹出」的回归测试。
// 缓存过期后轮询路径必须复用上次结果；一旦它掉进 probeLoginStatus，
// 就会 newBrowser() 真开一个浏览器 —— 测试里会直接挂住，由 -timeout 判失败。
func TestCheckLoginStatusReusesStaleResultInsteadOfProbing(t *testing.T) {
	saved := loginStatusCA
	defer func() { loginStatusCA = saved }()

	loginStatusCA = &statusCache{ttl: 0} // 强制过期
	loginStatusCA.set(&LoginStatusResponse{IsLoggedIn: true, Username: "上次结果"})

	svc := &XiaohongshuService{}
	got, err := svc.CheckLoginStatus(context.Background())
	if err != nil {
		t.Fatalf("不应返回错误，实际 %v", err)
	}
	if got == nil || got.Username != "上次结果" {
		t.Fatalf("过期后应复用上次结果而不是重新探测，实际 %+v", got)
	}
}
