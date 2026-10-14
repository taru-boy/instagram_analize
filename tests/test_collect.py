from collect import make_df, make_dict


def test_make_df():
    media = [
        {
            "id": "1",
            "media_type": "IMAGE",
            "media_url": "https://example.com/1.jpg",
            "caption": "新作です #水彩 #原画 #art",
            "timestamp": "2026-10-01T09:30:00+0000",
            "like_count": 10,
            "comments_count": 2,
        },
        {
            "id": "2",
            "media_type": "VIDEO",
            "media_url": "https://example.com/2.mp4",
            "thumbnail_url": "https://example.com/2.jpg",
            "timestamp": "2026-10-02T10:00:00+0000",
        },
    ]
    df = make_df(media, make_dict())
    assert df["id"].tolist() == ["1", "2"]
    assert df["hashtag"].tolist() == ["水彩\n原画\nart", ""]
    assert df["timestamp"].tolist() == ["2026-10-01 09:30:00", "2026-10-02 10:00:00"]
    # VIDEO はサムネイル、キャプションが無ければ空文字
    assert df.loc[1, "media_url"] == "https://example.com/2.jpg"
    assert df.loc[1, "caption"] == ""
    assert df["like_count"].isna().tolist() == [False, True]
