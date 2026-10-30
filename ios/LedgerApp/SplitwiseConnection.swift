import SwiftUI
import AuthenticationServices
import Security
import CryptoKit

@MainActor enum MobileCredential {
    private static var query: [String: Any] { [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "com.ashwin.splitwiseledger.mobile",
        kSecAttrAccount as String: SummaryConnection.backendURL ?? "unconfigured"
    ] }
    struct Session: Codable { let access_token: String; let user_id: Int }
    static func session() -> Session? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return try? JSONDecoder().decode(Session.self, from: data)
    }
    static func read() -> String? { session()?.access_token }
    static var identity: String {
        let value = "\(SummaryConnection.backendURL ?? "")|\(session()?.user_id ?? 0)"
        return SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    static func save(_ data: Data) throws {
        _ = try JSONDecoder().decode(Session.self, from: data)
        let update = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecSuccess { return }
        guard status == errSecItemNotFound else { throw SheetError.invalid("Could not save your sign-in securely.") }
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else {
            throw SheetError.invalid("Could not save your sign-in securely.")
        }
    }
    static func clear() { SecItemDelete(query as CFDictionary) }
}

struct MobileRequestError: LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { message }
}

@MainActor enum MobileAPI {
    static func url(_ path: String) throws -> URL {
        guard let base = SummaryConnection.backendURL,
              var parts = URLComponents(string: base),
              ["http", "https"].contains(parts.scheme ?? ""), parts.host != nil,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil else {
            throw SheetError.invalid("Minto’s server has not been configured for this build.")
        }
        guard let endpoint = URLComponents(string: path), endpoint.scheme == nil,
              endpoint.host == nil, endpoint.fragment == nil else { throw URLError(.badURL) }
        parts.path = "/" + ([parts.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")), "mobile", endpoint.path]
            .filter { !$0.isEmpty }.joined(separator: "/"))
        parts.queryItems = endpoint.queryItems
        guard let url = parts.url else { throw SheetError.invalid("Invalid server address.") }
        return url
    }
    static func request(_ path: String, method: String = "GET", body: Data? = nil,
                        authenticated: Bool = true) async throws -> Data {
        var request = URLRequest(url: try url(path), timeoutInterval: 90)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if authenticated {
            guard let token = MobileCredential.read() else { throw SheetError.invalid("Connect Splitwise first.") }
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard http.statusCode == 200 else {
            let detail = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw MobileRequestError(status: http.statusCode,
                                     message: detail?["detail"] as? String ?? "Minto’s server could not complete the request.")
        }
        return data
    }
}

@MainActor final class SplitwiseSignIn: NSObject, ASWebAuthenticationPresentationContextProviding {
    private var session: ASWebAuthenticationSession?
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows).first(where: \.isKeyWindow) ?? ASPresentationAnchor()
    }
    func run() async throws {
        struct Start: Decodable { let state: String; let verifier: String; let connection_path: String }
        let start = try JSONDecoder().decode(Start.self, from: await MobileAPI.request("auth/start", method: "POST", authenticated: false))
        var parts = URLComponents(url: try MobileAPI.url("auth/connect"), resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "state", value: start.state)]
        guard let url = parts.url else { throw URLError(.badURL) }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: "minto") { url, error in
                if let error { continuation.resume(throwing: error) }
                else if url?.host == "oauth", url?.path == "/complete" { continuation.resume() }
                else { continuation.resume(throwing: URLError(.badServerResponse)) }
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = true
            self.session = session
            if !session.start() { continuation.resume(throwing: SheetError.invalid("Could not open Splitwise sign-in.")) }
        }
        session = nil
        let body = try JSONSerialization.data(withJSONObject: ["state": start.state, "verifier": start.verifier])
        let data = try await MobileAPI.request("auth/exchange", method: "POST", body: body, authenticated: false)
        try MobileCredential.save(data)
    }
}
