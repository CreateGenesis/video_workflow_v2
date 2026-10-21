# cvgen-style

来源：官方 brand-promo、minimalist-product-ad、3d-animation-short、handdrawn-live、music-video-subtitle。这些原技能绑定 Hub，这里改成可锁定的 Style。

可用预设：品牌宣传、极简产品广告、三维动画短片、手绘结合实拍、歌词卡点。纸工艺和定格只作为反例，不写成正面要求。

操作：

- `cvgen entity add Style '{"title":"品牌宣传","medium":"真人电影感","grade":"统一光线和调色","ban":"禁止定格、字幕和水印"}'`
- `cvgen link styled_as <镜头> <风格>`
- 想从已有片子提取时，发 `cvgen style extract <成片>`，服务写回 Style。agent 再决定是否连到镜头。
