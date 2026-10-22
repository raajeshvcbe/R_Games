import unittest

from fastapi.testclient import TestClient

from app import main
from app.games.rummy.engine import Card


class RoomApiTests(unittest.TestCase):
    def setUp(self):
        main.sessions.clear()
        main.usernames.clear()
        main.rooms.clear()
        main.lobby_connections.clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.sessions.clear()
        main.usernames.clear()
        main.rooms.clear()
        main.lobby_connections.clear()

    def claim(self, username):
        response = self.client.post("/api/session", json={"username": username})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    @staticmethod
    def auth(token):
        return {"X-Session-Token": token}

    def test_username_is_unique_without_case_sensitivity(self):
        self.claim("Card Player")
        response = self.client.post("/api/session", json={"username": "card player"})
        self.assertEqual(response.status_code, 409)

    def test_public_room_create_join_capacity_and_host_transfer(self):
        host = self.claim("Host")
        guest = self.claim("Guest")
        third = self.claim("Third")
        response = self.client.post(
            "/api/rooms",
            headers=self.auth(host),
            json={
                "room_name": "Friday cards",
                "min_players": 2,
                "max_players": 2,
                "game_options": {"max_decks": 2},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        room = response.json()
        code = room["code"]
        self.assertEqual(room["name"], "Friday cards")
        self.assertEqual(room["game_options"]["max_decks"], 2)

        response = self.client.post(f"/api/rooms/{code}/join", headers=self.auth(guest))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["player_count"], 2)

        response = self.client.get("/api/rooms")
        self.assertEqual(response.json(), [])
        response = self.client.post(f"/api/rooms/{code}/join", headers=self.auth(third))
        self.assertEqual(response.status_code, 409)

        self.client.post(f"/api/rooms/{code}/leave", headers=self.auth(host))
        response = self.client.get(f"/api/rooms/{code}", headers=self.auth(guest))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["players"][0]["is_host"])

        self.client.post(f"/api/rooms/{code}/leave", headers=self.auth(guest))
        response = self.client.get(f"/api/rooms/{code}", headers=self.auth(guest))
        self.assertEqual(response.status_code, 404)

    def test_private_room_is_hidden_from_public_listing_and_joinable_by_code(self):
        host = self.claim("Host")
        guest = self.claim("Guest")
        response = self.client.post(
            "/api/rooms",
            headers=self.auth(host),
            json={"visibility": "private", "min_players": 2, "max_players": 4},
        )
        self.assertEqual(response.status_code, 200, response.text)
        code = response.json()["code"]
        self.assertEqual(self.client.get("/api/rooms").json(), [])

        response = self.client.post(f"/api/rooms/{code.lower()}/join", headers=self.auth(guest))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["visibility"], "private")

    def test_room_configuration_rejects_invalid_player_and_deck_counts(self):
        host = self.claim("Host")
        response = self.client.post(
            "/api/rooms",
            headers=self.auth(host),
            json={"min_players": 4, "max_players": 2},
        )
        self.assertEqual(response.status_code, 422)
        response = self.client.post(
            "/api/rooms",
            headers=self.auth(host),
            json={"game_options": {"max_decks": 5}},
        )
        self.assertEqual(response.status_code, 422)

    def test_display_name_change_is_reflected_in_room(self):
        host = self.claim("Username")
        room = self.client.post(
            "/api/rooms",
            headers=self.auth(host),
            json={},
        ).json()
        response = self.client.patch(
            "/api/me",
            headers=self.auth(host),
            json={"display_name": "New Name"},
        )
        self.assertEqual(response.status_code, 200)
        room = self.client.get(f"/api/rooms/{room['code']}", headers=self.auth(host)).json()
        self.assertEqual(room["players"][0]["display_name"], "New Name")

    def test_player_can_only_join_one_room_and_exit_releases_username(self):
        token = self.claim("Reusable")
        first_room = self.client.post(
            "/api/rooms",
            headers=self.auth(token),
            json={},
        ).json()
        response = self.client.post(
            "/api/rooms",
            headers=self.auth(token),
            json={},
        )
        self.assertEqual(response.status_code, 409)

        response = self.client.post("/api/session/exit", headers=self.auth(token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/rooms").json(), [])
        self.claim("Reusable")
        response = self.client.get(
            f"/api/rooms/{first_room['code']}",
            headers=self.auth(token),
        )
        self.assertEqual(response.status_code, 401)

    def test_lobby_websocket_receives_room_change(self):
        host = self.claim("Host")
        with self.client.websocket_connect(f"/ws/lobby?token={host}") as websocket:
            self.client.post("/api/rooms", headers=self.auth(host), json={})
            message = websocket.receive_json()
        self.assertEqual(message, {"type": "state_changed"})

    def test_rummy_turns_hide_opponents_hands_and_declaration_scores(self):
        host = self.claim("Host")
        guest = self.claim("Guest")
        room = self.client.post(
            "/api/rooms",
            headers=self.auth(host),
            json={"game_options": {"scoring_mode": "points", "max_decks": 2}},
        ).json()
        code = room["code"]
        self.client.post(f"/api/rooms/{code}/join", headers=self.auth(guest))

        response = self.client.post(f"/api/rooms/{code}/start", headers=self.auth(guest))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(f"/api/rooms/{code}/start", headers=self.auth(host))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["game"]["own_hand"]), 13)

        guest_view = self.client.get(f"/api/rooms/{code}", headers=self.auth(guest)).json()
        self.assertEqual(len(guest_view["game"]["own_hand"]), 13)
        self.assertNotIn("hands", guest_view["game"])
        response = self.client.post(
            f"/api/rooms/{code}/draw",
            headers=self.auth(guest),
            json={"source": "stock"},
        )
        self.assertEqual(response.status_code, 409)

        response = self.client.post(
            f"/api/rooms/{code}/draw",
            headers=self.auth(host),
            json={"source": "stock"},
        )
        self.assertEqual(len(response.json()["game"]["own_hand"]), 14)
        card_id = response.json()["game"]["own_hand"][0]["id"]
        response = self.client.post(
            f"/api/rooms/{code}/discard",
            headers=self.auth(host),
            json={"card_id": card_id},
        )
        self.assertEqual(response.json()["game"]["turn_name"], "Guest")
        self.assertEqual(response.json()["game"]["phase"], "draw")

        valid_winning_hand = [
            Card("ha", 1, "hearts"),
            Card("h2", 2, "hearts"),
            Card("h3", 3, "hearts"),
            Card("c4", 4, "clubs"),
            Card("c5", 5, "clubs"),
            Card("c6", 6, "clubs"),
            Card("c8", 8, "clubs"),
            Card("d8", 8, "diamonds"),
            Card("h8", 8, "hearts"),
            Card("c9", 9, "clubs"),
            Card("d9", 9, "diamonds"),
            Card("h9", 9, "hearts"),
            Card("s9", 9, "spades"),
        ]
        game = main.rooms[code]["game"]
        game["hands"][host] = valid_winning_hand + [Card("spare", 7, "spades")]
        game["hands"][guest] = [
            Card(f"penalty-{index}", 10, ("clubs", "diamonds", "hearts", "spades")[index % 4])
            for index in range(13)
        ]
        game["turn_token"] = host
        game["phase"] = "discard"
        response = self.client.post(
            f"/api/rooms/{code}/declare",
            headers=self.auth(host),
            json={"card_ids": [card.card_id for card in valid_winning_hand]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["game"]
        self.assertEqual(result["status"], "complete")
        scores = {player["display_name"]: player["score"] for player in result["round_result"]}
        self.assertEqual(scores, {"Host": 0, "Guest": 80})
        self.assertEqual(result["winner_names"], ["Host"])

    def test_scoring_modes_store_only_their_relevant_room_options(self):
        deals_host = self.claim("DealsHost")
        deals = self.client.post(
            "/api/rooms",
            headers=self.auth(deals_host),
            json={"game_options": {"scoring_mode": "deals", "deal_count": 3}},
        ).json()
        self.assertEqual(deals["game_options"]["deal_count"], 3)
        self.assertIsNone(deals["game_options"]["pool_limit"])

        pool_host = self.claim("PoolHost")
        pool = self.client.post(
            "/api/rooms",
            headers=self.auth(pool_host),
            json={"game_options": {"scoring_mode": "pool", "pool_limit": 201}},
        ).json()
        self.assertEqual(pool["game_options"]["pool_limit"], 201)
        self.assertIsNone(pool["game_options"]["deal_count"])

        custom_pool_host = self.claim("CustomPoolHost")
        custom_pool = self.client.post(
            "/api/rooms",
            headers=self.auth(custom_pool_host),
            json={"game_options": {"scoring_mode": "pool", "pool_limit": 350}},
        )
        self.assertEqual(custom_pool.status_code, 200, custom_pool.text)
        self.assertEqual(custom_pool.json()["game_options"]["pool_limit"], 350)

        missing_limit_host = self.claim("MissingPoolLimit")
        missing_limit = self.client.post(
            "/api/rooms",
            headers=self.auth(missing_limit_host),
            json={"game_options": {"scoring_mode": "pool"}},
        )
        self.assertEqual(missing_limit.status_code, 422)

        large_custom_limit = "9" * 100
        large_pool_host = self.claim("LargePoolHost")
        large_pool = self.client.post(
            "/api/rooms",
            headers=self.auth(large_pool_host),
            json={"game_options": {"scoring_mode": "pool", "pool_limit": large_custom_limit}},
        )
        self.assertEqual(large_pool.status_code, 200, large_pool.text)
        self.assertEqual(large_pool.json()["game_options"]["pool_limit"], large_custom_limit)

        for invalid_limit in (0, -1, 1.5, True):
            with self.subTest(invalid_pool_limit=invalid_limit):
                invalid_host = self.claim(f"InvalidPool{str(invalid_limit).replace('.', '')}")
                response = self.client.post(
                    "/api/rooms",
                    headers=self.auth(invalid_host),
                    json={"game_options": {"scoring_mode": "pool", "pool_limit": invalid_limit}},
                )
                self.assertEqual(response.status_code, 422)

    def test_deals_and_pool_formats_progress_between_rounds(self):
        for mode, options in (
            ("deals", {"deal_count": 2}),
            ("pool", {"pool_limit": 101}),
        ):
            with self.subTest(mode=mode):
                main.sessions.clear()
                main.usernames.clear()
                main.rooms.clear()
                host = self.claim(f"{mode}Host")
                guest = self.claim(f"{mode}Guest")
                room = self.client.post(
                    "/api/rooms",
                    headers=self.auth(host),
                    json={"game_options": {"scoring_mode": mode, **options}},
                ).json()
                code = room["code"]
                self.client.post(f"/api/rooms/{code}/join", headers=self.auth(guest))
                self.client.post(f"/api/rooms/{code}/start", headers=self.auth(host))

                for deal in range(2):
                    game = main.rooms[code]["game"]
                    game["wild_rank"] = 13
                    valid_hand = [
                        Card("ha", 1, "hearts"),
                        Card("h2", 2, "hearts"),
                        Card("h3", 3, "hearts"),
                        Card("c4", 4, "clubs"),
                        Card("c5", 5, "clubs"),
                        Card("c6", 6, "clubs"),
                        Card("c8", 8, "clubs"),
                        Card("d8", 8, "diamonds"),
                        Card("h8", 8, "hearts"),
                        Card("c9", 9, "clubs"),
                        Card("d9", 9, "diamonds"),
                        Card("h9", 9, "hearts"),
                        Card("s9", 9, "spades"),
                    ]
                    game["hands"][host] = valid_hand + [Card(f"spare-{deal}", 7, "spades")]
                    game["hands"][guest] = [
                        Card(f"penalty-{deal}-{index}", 10, ("clubs", "diamonds", "hearts", "spades")[index % 4])
                        for index in range(13)
                    ]
                    game["turn_token"] = host
                    game["phase"] = "discard"
                    response = self.client.post(
                        f"/api/rooms/{code}/declare",
                        headers=self.auth(host),
                        json={"card_ids": [card.card_id for card in valid_hand]},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()["game"]
                    if deal == 0:
                        self.assertEqual(result["status"], "round_over")
                        response = self.client.post(
                            f"/api/rooms/{code}/next-round",
                            headers=self.auth(host),
                        )
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()["game"]["round_number"], 2)
                    else:
                        self.assertEqual(result["status"], "complete")
                        self.assertEqual(result["winner_names"], [f"{mode}Host"])


if __name__ == "__main__":
    unittest.main()
