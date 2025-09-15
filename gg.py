from web3 import Web3
from web3.exceptions import TransactionNotFound
from eth_account import Account
from eth_abi.abi import encode
from dotenv import load_dotenv
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from aiohttp import ClientResponseError, ClientSession, ClientTimeout
from fake_useragent import FakeUserAgent  # <-- Ditambahkan kembali
from datetime import datetime
from colorama import *
import asyncio, binascii, random, json, os, pytz

# Inisialisasi Colorama dan Dotenv
load_dotenv()
init(autoreset=True)

# Atur zona waktu
wib = pytz.timezone('Asia/Jakarta')

class KiteAICron:
    def __init__(self) -> None:
        # --- Konfigurasi dari .env ---
        self.ai_chat_count = int(os.getenv("AI_CHAT_COUNT", 5))
        self.multisig_count = int(os.getenv("MULTISIG_COUNT", 2))
        self.min_delay = int(os.getenv("MIN_DELAY", 30))
        self.max_delay = int(os.getenv("MAX_DELAY", 60))

        # --- Alamat Kontrak & Konfigurasi Blockchain ---
        self.ZERO_CONTRACT_ADDRESS = "0x0000000000000000000000000000000000000000"
        self.SAFE_PROXY_FACTORY_ADDRESS = "0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2"
        self.GNOSIS_SAFE_L2_ADDRESS = "0x3E5c63644E683549055b9Be8653de26E0B4CD36E"
        self.FALLBACK_HANDLER_ADDRESS = "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4"
        self.KITE_AI_RPC = "https://rpc-testnet.gokite.ai/"
        self.KITE_AI_EXPLORER = "https://testnet.kitescan.ai/tx/"
        
        # --- API Endpoints ---
        self.NEO_API = "https://neo.prod.gokite.ai"
        self.OZONE_API = "https://ozone-point-system.prod.gokite.ai"
        self.MULTISIG_API = "https://wallet-client.ash.center/v1"

        # --- ABI yang Dibutuhkan ---
        self.ERC20_CONTRACT_ABI = json.loads('''[
            {"type":"function","name":"createProxyWithNonce","stateMutability":"nonpayable","inputs":[{"internalType":"address","name":"_singleton","type":"address"},{"internalType":"bytes","name":"initializer","type":"bytes"},{"internalType":"uint256","name":"saltNonce","type":"uint256"}],"outputs":[{"internalType":"contract GnosisSafeProxy","name":"proxy","type":"address"}]}
        ]''')

        # --- State Management per Akun ---
        self.TESTNET_HEADERS = {}
        self.MULTISIG_HEADERS = {}
        self.auth_tokens = {}
        self.access_tokens = {}
        self.aa_address = {}

    def log(self, message):
        """Mencetak log dengan timestamp."""
        print(f"{Fore.CYAN+Style.BRIGHT}[ {datetime.now(wib).strftime('%Y-%m-%d %H:%M:%S')} ]{Style.RESET_ALL} {message}")

    def load_ai_agents(self):
        """Memuat daftar AI agent dari file agents.json."""
        try:
            with open("agents.json", 'r') as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.log(f"{Fore.RED}Gagal memuat agents.json. Pastikan file ada dan formatnya benar.")
            return []

    def generate_address(self, private_key: str):
        """Menghasilkan alamat Ethereum dari private key."""
        try:
            return Account.from_key(private_key).address
        except Exception:
            return None
    
    def mask_address(self, address: str):
        """Menyamarkan alamat untuk ditampilkan di log."""
        return f"{address[:6]}...{address[-4:]}"

    def generate_auth_token(self, address: str):
        """Menghasilkan token otentikasi untuk API."""
        try:
            key = bytes.fromhex("6a1c35292b7c5b769ff47d89a17e7bc4f0adfe1b462981d28e0e9f7ff20b8f8a")
            iv = os.urandom(12)
            encryptor = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend()).encryptor()
            ciphertext = encryptor.update(address.encode()) + encryptor.finalize()
            return binascii.hexlify(iv + ciphertext + encryptor.tag).decode()
        except Exception as e:
            self.log(f"{Fore.RED}Gagal membuat auth token: {e}")
            return None

    async def print_delay(self, message: str):
        """Memberikan jeda waktu acak antara min dan max delay."""
        delay = random.randint(self.min_delay, self.max_delay)
        for i in range(delay, 0, -1):
            print(f"{Fore.YELLOW}Jeda {i} detik sebelum {message} berikutnya...     ", end="\r", flush=True)
            await asyncio.sleep(1)
        print("                                                          ", end="\r")

    # =================================================================
    # METODE API (AIOHTTP)
    # =================================================================

    async def user_signin(self, address: str, retries=3):
        url = f"{self.NEO_API}/v2/signin"
        headers = {**self.TESTNET_HEADERS[address], "Authorization": self.auth_tokens[address], "Content-Type": "application/json"}
        for attempt in range(retries):
            try:
                async with ClientSession(timeout=ClientTimeout(total=60)) as session:
                    async with session.post(url, headers=headers, json={"eoa": address}) as response:
                        response.raise_for_status()
                        return await response.json()
            except Exception as e:
                if attempt < retries - 1: await asyncio.sleep(5)
                else: self.log(f"{Fore.RED}Gagal sign in setelah {retries} percobaan: {e}")
        return None

    async def user_data(self, address: str, retries=3):
        url = f"{self.OZONE_API}/me"
        headers = {**self.TESTNET_HEADERS[address], "Authorization": f"Bearer {self.access_tokens[address]}"}
        for attempt in range(retries):
            try:
                async with ClientSession(timeout=ClientTimeout(total=60)) as session:
                    async with session.get(url, headers=headers) as response:
                        response.raise_for_status()
                        return await response.json()
            except Exception as e:
                if attempt < retries - 1: await asyncio.sleep(5)
                else: self.log(f"{Fore.RED}Gagal mengambil data user: {e}")
        return None

    async def agent_inference(self, address: str, service_id: str, question: str, retries=3):
        url = f"{self.OZONE_API}/agent/inference"
        payload = {"service_id": service_id, "subnet": "kite_ai_labs", "stream": True, "body": {"stream": True, "message": question}}
        headers = {**self.TESTNET_HEADERS[address], "Authorization": f"Bearer {self.access_tokens[address]}", "Content-Type": "application/json"}
        for attempt in range(retries):
            try:
                async with ClientSession(timeout=ClientTimeout(total=120)) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        result = ""
                        async for line in response.content:
                            line = line.decode("utf-8").strip()
                            if line.startswith("data:"):
                                if line == "data: [DONE]": break
                                try:
                                    json_data = json.loads(line[len("data:"):].strip())
                                    content = json_data.get("choices", [{}])[0].get("delta", {}).get("content")
                                    if content: result += content
                                except json.JSONDecodeError: continue
                        return result.strip()
            except Exception as e:
                if attempt < retries - 1: await asyncio.sleep(5)
                else: self.log(f"{Fore.RED}Gagal berinteraksi dengan AI agent: {e}")
        return None

    async def submit_receipt(self, address: str, service_id: str, question: str, answer: str, retries=3):
        url = f"{self.NEO_API}/v2/submit_receipt"
        payload = {"address": self.aa_address[address], "service_id": service_id, "input": [{"type": "text/plain", "value": question}], "output": [{"type": "text/plain", "value": answer}]}
        headers = {**self.TESTNET_HEADERS[address], "Authorization": f"Bearer {self.access_tokens[address]}", "Content-Type": "application/json"}
        for attempt in range(retries):
            try:
                async with ClientSession(timeout=ClientTimeout(total=60)) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        return await response.json()
            except Exception as e:
                if attempt < retries - 1: await asyncio.sleep(5)
                else: self.log(f"{Fore.RED}Gagal mengirim receipt: {e}")
        return None

    async def get_inference(self, address: str, inference_id: str, retries=3):
        url = f"{self.NEO_API}/v1/inference?id={inference_id}"
        headers = {**self.TESTNET_HEADERS[address], "Authorization": f"Bearer {self.access_tokens[address]}"}
        for attempt in range(retries):
            try:
                async with ClientSession(timeout=ClientTimeout(total=60)) as session:
                    async with session.get(url, headers=headers) as response:
                        response.raise_for_status()
                        result = await response.json()
                        tx_hash = result.get("data", {}).get("tx_hash")
                        if not tx_hash: raise Exception("Tx hash belum tersedia")
                        return tx_hash
            except Exception as e:
                if attempt < retries - 1: await asyncio.sleep(10) # Give more time for tx hash to appear
                else: self.log(f"{Fore.RED}Gagal mendapatkan inference tx hash: {e}")
        return None

    async def owner_safes_wallet(self, address: str, retries=3):
        url = f"{self.MULTISIG_API}/chains/2368/owners/{address}/safes"
        for attempt in range(retries):
            try:
                async with ClientSession(timeout=ClientTimeout(total=60)) as session:
                    async with session.get(url, headers=self.MULTISIG_HEADERS[address]) as response:
                        response.raise_for_status()
                        return await response.json()
            except Exception as e:
                if attempt < retries - 1: await asyncio.sleep(5)
                else: self.log(f"{Fore.RED}Gagal mengambil data safes wallet: {e}")
        return None

    # =================================================================
    # METODE ON-CHAIN (WEB3)
    # =================================================================

    async def get_web3(self):
        try:
            web3 = Web3(Web3.HTTPProvider(self.KITE_AI_RPC))
            if web3.is_connected():
                return web3
            raise ConnectionError("RPC Connection Failed")
        except Exception as e:
            self.log(f"{Fore.RED}Gagal terhubung ke RPC: {e}")
            return None

    async def send_raw_transaction(self, account_pk: str, web3: Web3, tx: dict, retries=5):
        for attempt in range(retries):
            try:
                signed_tx = web3.eth.account.sign_transaction(tx, account_pk)
                tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
                receipt = await asyncio.to_thread(web3.eth.wait_for_transaction_receipt, tx_hash, timeout=300)
                if receipt.status == 1:
                    return web3.to_hex(tx_hash)
                else:
                    self.log(f"{Fore.RED}Transaksi gagal di blockchain (status 0).")
                    return None
            except TransactionNotFound:
                self.log(f"{Fore.YELLOW}Transaksi tidak ditemukan, mencoba lagi... ({attempt+1}/{retries})")
                await asyncio.sleep(3)
            except Exception as e:
                self.log(f"{Fore.RED}Error saat mengirim transaksi: {e}")
                await asyncio.sleep(2 ** attempt)
        self.log(f"{Fore.RED}Gagal mengirim transaksi setelah {retries} percobaan.")
        return None

    def build_initializer_data(self, address: str):
        prefix = bytes.fromhex("b63e800d")
        encoded_params = encode(
            ['address[]', 'uint256', 'address', 'bytes', 'address', 'address', 'uint256', 'address'],
            [[address], 1, self.ZERO_CONTRACT_ADDRESS, b"", self.FALLBACK_HANDLER_ADDRESS, self.ZERO_CONTRACT_ADDRESS, 0, self.ZERO_CONTRACT_ADDRESS]
        )
        return prefix + encoded_params

    async def perform_create_proxy(self, account: str, address: str, salt_nonce: int):
        web3 = await self.get_web3()
        if not web3: return None

        try:
            initializer = self.build_initializer_data(address)
            factory_contract = web3.eth.contract(address=web3.to_checksum_address(self.SAFE_PROXY_FACTORY_ADDRESS), abi=self.ERC20_CONTRACT_ABI)
            
            tx_data = factory_contract.functions.createProxyWithNonce(self.GNOSIS_SAFE_L2_ADDRESS, initializer, salt_nonce)
            
            gas = tx_data.estimate_gas({"from": address})
            max_priority_fee = web3.to_wei(0.001, "gwei")

            tx = tx_data.build_transaction({
                "from": address,
                "gas": int(gas * 1.2),
                "maxFeePerGas": max_priority_fee,
                "maxPriorityFeePerGas": max_priority_fee,
                "nonce": web3.eth.get_transaction_count(address),
                "chainId": web3.eth.chain_id,
            })

            return await self.send_raw_transaction(account, web3, tx)
        except Exception as e:
            self.log(f"{Fore.RED}Gagal membuat proxy: {e}")
            return None

    # =================================================================
    # PROSES UTAMA
    # =================================================================

    async def run_ai_agent_interaction(self, address: str, agent_lists: list):
        self.log(f"{Fore.CYAN+Style.BRIGHT}--- Memulai Interaksi AI Agent ---")
        if not agent_lists:
            self.log(f"{Fore.RED}Tidak ada AI agent yang dimuat, melewati tugas ini.")
            return

        for i in range(self.ai_chat_count):
            self.log(f"{Fore.WHITE}Interaksi ke-{i+1} dari {self.ai_chat_count}...")
            
            agent = random.choice(agent_lists)
            question = random.choice(agent["questionLists"])
            
            self.log(f"  {Fore.BLUE}Agent    : {Style.RESET_ALL}{agent['agentName']}")
            self.log(f"  {Fore.BLUE}Pertanyaan: {Style.RESET_ALL}{question}")

            answer = await self.agent_inference(address, agent["serviceId"], question)
            if not answer: continue

            self.log(f"  {Fore.GREEN}Jawaban  : {Style.RESET_ALL}{answer[:80]}...")

            receipt = await self.submit_receipt(address, agent["serviceId"], question, answer)
            if receipt:
                inference_id = receipt.get("data", {}).get("id")
                self.log(f"  {Fore.GREEN}Receipt berhasil dikirim (ID: {inference_id}). Mencari tx hash...")
                tx_hash = await self.get_inference(address, inference_id)
                if tx_hash:
                    self.log(f"  {Fore.GREEN}Transaksi Sukses! Hash: {self.KITE_AI_EXPLORER}{tx_hash}")
                else:
                    self.log(f"  {Fore.YELLOW}Gagal mendapatkan tx hash untuk inference ID {inference_id}.")
            
            await self.print_delay("interaksi AI")
        self.log(f"{Fore.CYAN+Style.BRIGHT}--- Selesai Interaksi AI Agent ---")

    async def run_multisig_creation(self, account: str, address: str):
        self.log(f"{Fore.CYAN+Style.BRIGHT}--- Memulai Pembuatan Multisig Wallet ---")
        for i in range(self.multisig_count):
            self.log(f"{Fore.WHITE}Membuat multisig ke-{i+1} dari {self.multisig_count}...")

            safes = await self.owner_safes_wallet(address)
            if safes is None: continue

            salt_nonce = len(safes.get("safes", []))
            self.log(f"  Salt Nonce yang akan digunakan: {salt_nonce}")

            tx_hash = await self.perform_create_proxy(account, address, salt_nonce)
            if tx_hash:
                self.log(f"  {Fore.GREEN}Transaksi Sukses! Hash: {self.KITE_AI_EXPLORER}{tx_hash}")
            else:
                self.log(f"  {Fore.RED}Gagal melakukan transaksi on-chain untuk pembuatan proxy.")

            await self.print_delay("pembuatan multisig")
        self.log(f"{Fore.CYAN+Style.BRIGHT}--- Selesai Pembuatan Multisig Wallet ---")

    async def run_tasks_for_account(self, private_key: str, agent_lists: list):
        address = self.generate_address(private_key)
        if not address:
            self.log(f"{Fore.RED}Private key tidak valid.")
            return

        self.log(f"\n{Fore.YELLOW+Style.BRIGHT}================ Mengerjakan Akun: {self.mask_address(address)} ================")
        
        # --- PERBAIKAN: Membuat header yang lengkap ---
        try:
            user_agent = FakeUserAgent().random
        except Exception:
            # Fallback jika FakeUserAgent gagal (misal, tidak bisa fetch dari server)
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

        self.TESTNET_HEADERS[address] = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://testnet.gokite.ai",
            "Referer": "https://testnet.gokite.ai/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": user_agent
        }
        self.MULTISIG_HEADERS[address] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://wallet.ash.center",
            "Referer": "https://wallet.ash.center/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": user_agent
        }
        # --- AKHIR PERBAIKAN ---

        self.auth_tokens[address] = self.generate_auth_token(address)
        if not self.auth_tokens[address]: return

        # Proses Sign In
        signin_data = await self.user_signin(address)
        if not signin_data: return
        self.access_tokens[address] = signin_data["data"]["access_token"]
        self.aa_address[address] = signin_data["data"]["aa_address"]
        self.log(f"{Fore.GREEN}Login berhasil. AA Address: {self.mask_address(self.aa_address[address])}")

        # Menampilkan data user
        user_info = await self.user_data(address)
        if user_info:
            profile = user_info.get("data", {}).get("profile", {})
            self.log(f"  Username: {profile.get('username', 'N/A')}, Poin V2: {profile.get('total_xp_points', 0)} XP, Rank: {profile.get('rank', 0)}")

        # Jalankan tugas yang diminta
        await self.run_ai_agent_interaction(address, agent_lists)
        await self.run_multisig_creation(private_key, address)

    async def main(self):
        try:
            with open('accounts.txt', 'r') as file:
                accounts = [line.strip() for line in file if line.strip()]
        except FileNotFoundError:
            self.log(f"{Fore.RED}File 'accounts.txt' tidak ditemukan. Harap buat file tersebut.")
            return

        agent_lists = self.load_ai_agents()
        if not agent_lists: return

        self.log(f"Total Akun: {len(accounts)}")
        self.log(f"Tugas per Akun: {self.ai_chat_count}x AI Chat, {self.multisig_count}x Multisig")
        self.log(f"Jeda Waktu: {self.min_delay}-{self.max_delay} detik")
        
        for account in accounts:
            await self.run_tasks_for_account(account, agent_lists)

        self.log(f"\n{Fore.GREEN+Style.BRIGHT}Semua akun telah diproses. Skrip akan selesai.")

if __name__ == "__main__":
    bot = KiteAICron()
    try:
        asyncio.run(bot.main())
    except KeyboardInterrupt:
        print("\nProses dihentikan oleh pengguna.")
